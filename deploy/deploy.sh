#!/usr/bin/env bash
# Deploy one commit of Fateweave on the OCI VM: backup → build → migrate → restart → health check.
# Called by .github/workflows/deploy.yml over SSH, or by hand:
#   sudo /opt/fateweave/deploy/deploy.sh <commit-sha>
#
# Settings (environment, all optional):
#   FATEWEAVE_DIR          repo checkout on the VM (default /opt/fateweave)
#   FATEWEAVE_DEPLOY_ENV   root-owned file, mode 600, never committed (default
#                          /etc/fateweave/deploy.env). It holds the MIGRATION credentials:
#                            FATEWEAVE_DATABASE_URL=postgresql+asyncpg://fateweave_owner:...@host.docker.internal:5432/fateweave
#                          and, to take a backup before every migration (recommended; needs a
#                          host pg_dump at least as new as the server, e.g. postgresql-client-16):
#                            BACKUP_DIR=/var/backups/fateweave PGHOST=127.0.0.1
#                            PGUSER=fateweave_owner PGPASSFILE=/etc/fateweave/pgpass
#                          The runtime app credentials stay in /etc/fateweave/fateweave.env.
#   HEALTH_TIMEOUT         seconds to wait for a healthy container (default 120)
#   FATEWEAVE_EDGE_PROXY   container of the VM's TLS edge proxy (default my-flight-friend-caddy-1).
#                          After a restart it is reloaded so it re-resolves fateweave-api, then
#                          https://$FATEWEAVE_PUBLIC_HOST/healthz is checked through it.
#
# The commit must be reachable from origin/master. On a failed health check the previous commit
# is rebuilt and restarted. The schema is not rolled back (migrations are forward-compatible;
# restore the pre-deploy dump if a migration itself is bad — see README, Rollback).
set -euo pipefail
# The checkout is copied into the image and read there by an unprivileged user, so files written
# by git must stay world-readable (a 077 umask breaks the app with PermissionError).
umask 022

# Everything runs inside main(): bash parses the whole function before running it, so checking
# out another commit (which rewrites this file) cannot change the script mid-run.
main() {
    REF="${1:?usage: deploy.sh <commit-sha>}"
    DIR="${FATEWEAVE_DIR:-/opt/fateweave}"
    DEPLOY_ENV="${FATEWEAVE_DEPLOY_ENV:-/etc/fateweave/deploy.env}"
    HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"
    BRANCH=origin/master

    case "$REF" in
        *[!0-9a-f]* | '') echo "ref must be a hex commit sha" >&2; exit 2 ;;
    esac

    cd "$DIR"
    exec 9>/var/lock/fateweave-deploy.lock
    flock -n 9 || { echo "another deploy is running" >&2; exit 3; }

    compose() { docker compose -p fateweave -f deploy/compose.fateweave.yaml "$@"; }

    wait_healthy() {
        local waited=0 status
        while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
            status=$(docker inspect fateweave-api --format '{{.State.Health.Status}}' 2>/dev/null || true)
            if [ "$status" = healthy ] && curl -fsS -o /dev/null http://127.0.0.1:8080/healthz; then
                return 0
            fi
            sleep 5
            waited=$((waited + 5))
        done
        return 1
    }

    # The public path is edge proxy (Caddy, another compose project) -> fateweave-api:8080 on the
    # shared edge network. A recreated container gets a new IP that Caddy may not re-resolve, so
    # reload it (graceful, --force even with an unchanged config) and check the domain end to end.
    check_edge() {
        local proxy="${FATEWEAVE_EDGE_PROXY:-my-flight-friend-caddy-1}" host
        host=$(grep -E '^FATEWEAVE_PUBLIC_HOST=' "${FATEWEAVE_ENV_FILE:-/etc/fateweave/fateweave.env}" \
            | head -1 | cut -d= -f2- | tr -d "\"'" || true)
        if docker inspect "$proxy" >/dev/null 2>&1; then
            docker exec "$proxy" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile --force --address 127.0.0.1:2019 \
                >/dev/null 2>&1 || echo "warning: could not reload $proxy" >&2
        else
            echo "warning: edge proxy container $proxy not found; skipping reload" >&2
        fi
        if [ -z "$host" ]; then
            echo "warning: FATEWEAVE_PUBLIC_HOST not found; skipping the public check" >&2
            return 0
        fi
        for _ in 1 2 3 4 5 6 7 8; do
            if curl -fsS -o /dev/null --max-time 5 --resolve "$host:443:127.0.0.1" "https://$host/healthz"; then
                echo "public path ok: https://$host/healthz"
                return 0
            fi
            sleep 5
        done
        echo "error: https://$host/healthz fails through the edge proxy although the container is" \
            "healthy; check that $proxy reaches fateweave-api:8080 on the edge network" >&2
        return 6
    }

    git fetch --quiet origin
    # Never overwrite work that exists only on the VM: the running checkout must be a commit on
    # origin/master with no local edits. (A local, unpushed branch was once deployed over this way
    # and its feature silently disappeared.)
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
        echo "the checkout in $DIR has local changes; commit and push them (or discard) first" >&2
        exit 7
    fi
    if ! git merge-base --is-ancestor HEAD "$BRANCH"; then
        echo "the running checkout $(git rev-parse --short HEAD) is not on $BRANCH (local commits?);" \
            "push them through a PR first, or check out a $BRANCH commit deliberately" >&2
        exit 7
    fi
    if ! git merge-base --is-ancestor "$REF" "$BRANCH"; then
        echo "commit $REF is not on $BRANCH; refusing to deploy" >&2
        exit 4
    fi
    previous=$(git rev-parse HEAD)
    echo "deploying $REF (previous $previous)"
    # Until the new version is started, any failure puts the checkout back on the running commit,
    # so a retry still knows which commit to roll back to.
    restore="$previous"
    trap 'if [ -n "$restore" ]; then git checkout --quiet --detach "$restore"; echo "checkout restored to $restore" >&2; fi' EXIT
    git checkout --quiet --detach "$REF"

    compose build --pull

    if [ ! -r "$DEPLOY_ENV" ]; then
        echo "missing $DEPLOY_ENV (migration credentials); see the header of this script" >&2
        exit 5
    fi
    # Owner credentials come from the root-only file and reach the one-off migration container through
    # the environment, never argv. They are unset before the app restarts.
    set -a
    # shellcheck source=/dev/null
    . "$DEPLOY_ENV"
    set +a
    if [ -n "${BACKUP_DIR:-}" ]; then
        sh deploy/backup.sh
    else
        echo "warning: BACKUP_DIR not set in $DEPLOY_ENV; migrating without a fresh backup" >&2
    fi
    compose run --rm -e FATEWEAVE_DATABASE_URL fateweave-api alembic upgrade head
    unset FATEWEAVE_DATABASE_URL PGPASSWORD

    restore=""
    compose up -d
    if wait_healthy; then
        echo "deployed $REF: healthy"
        check_edge
        exit $?
    fi

    echo "health check failed for $REF; rolling the app back to $previous" >&2
    git checkout --quiet --detach "$previous"
    compose build
    compose up -d
    if wait_healthy; then
        echo "rolled back to $previous: healthy" >&2
    else
        echo "rollback to $previous is NOT healthy; manual action needed" >&2
    fi
    exit 1
}

main "$@"
