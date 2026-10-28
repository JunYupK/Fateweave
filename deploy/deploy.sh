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
#                          and, to take a backup before every migration (recommended):
#                            BACKUP_DIR=/var/backups/fateweave PGHOST=127.0.0.1
#                            PGUSER=fateweave_owner PGPASSFILE=/etc/fateweave/pgpass
#                          The runtime app credentials stay in /etc/fateweave/fateweave.env.
#   HEALTH_TIMEOUT         seconds to wait for a healthy container (default 120)
#
# The commit must be reachable from origin/master. On a failed health check the previous commit
# is rebuilt and restarted. The schema is not rolled back (migrations are forward-compatible;
# restore the pre-deploy dump if a migration itself is bad — see README, Rollback).
set -euo pipefail
umask 077

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

    git fetch --quiet origin
    if ! git merge-base --is-ancestor "$REF" "$BRANCH"; then
        echo "commit $REF is not on $BRANCH; refusing to deploy" >&2
        exit 4
    fi
    previous=$(git rev-parse HEAD)
    echo "deploying $REF (previous $previous)"
    git checkout --quiet --detach "$REF"

    compose build --pull

    if [ ! -r "$DEPLOY_ENV" ]; then
        echo "missing $DEPLOY_ENV (migration credentials); see the header of this script" >&2
        git checkout --quiet --detach "$previous"
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

    compose up -d
    if wait_healthy; then
        echo "deployed $REF: healthy"
        exit 0
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
