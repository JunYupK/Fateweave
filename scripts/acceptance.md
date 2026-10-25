# Deployment acceptance checks (Task 12)

Run from the repo root. Items marked **pending manual (R4)** need the real OCI VM and were NOT
executed by the implementer (no remote access). Do not paste real secrets into tickets or logs.

## A. Local / offline (verified in the repo environment)

1. Compose file validates (quiet mode; the env file path is a local, uncommitted file):
   `FATEWEAVE_ENV_FILE=/path/to/dummy.env docker compose -p fateweave -f deploy/compose.fateweave.yaml config -q`
   NEVER save or paste the full `docker compose config` output: Compose inlines `env_file`
   contents (including `FATEWEAVE_MCP_KEY` and the DB password) into it.
2. Image builds: `docker build -f deploy/Dockerfile -t fateweave-api:local .`
3. Disposable Postgres smoke test: start `postgres:16-alpine` on 127.0.0.1:55432, run
   `deploy/postgres-init.sql`, `alembic upgrade head` as `fateweave_owner`, re-run the init SQL,
   then `deploy/backup.sh` and `deploy/restore-check.sh <dump>`; stop the container.
4. Role privileges (as superuser, `SET ROLE fateweave_app`): INSERT on `birth_profiles` ok,
   UPDATE on `analysis_runs` ok, DELETE/UPDATE on `report_versions` and
   `alternative_interpretations` denied, TRUNCATE denied, CREATE TABLE denied, `alembic_version`
   unreadable.

## B. Live OCI checks - pending manual (R4)

Before enabling the container:

- [ ] **Resource headroom**: `free -m`, `df -h /var/lib/docker /var/backups`, `docker stats --no-stream`;
      confirm room for the 384 MB / 0.5 CPU limit next to Flight Friend.
- [ ] **Existing setup inventory (read-only)**: `docker ps`, `docker network ls`, `nginx -T | grep server_name`,
      `ss -ltnp | grep :8080` (port 8080 must be free; otherwise change the host side of the port mapping and the
      Nginx `proxy_pass` together).
- [ ] **Cert coverage**: if reusing a certificate, `openssl x509 -in <cert> -noout -ext subjectAltName` lists the public host.
- [ ] **DB bootstrap** by a DBA with `deploy/postgres-init.sql` (before and after migrations).

After deployment (replace `$HOST` with the public host, key from the secret file, never inline in shell history):

- [ ] `curl -sS -o /dev/null -w '%{http_code}\n' https://$HOST/healthz` -> `200`
- [ ] `curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://$HOST/mcp` (no key) -> `401`
- [ ] Token-authorized MCP `tools/list` through a real MCP client (header `X-Fateweave-Key`) lists the Fateweave tools.
- [ ] `curl -sI -H 'X-Fateweave-Key: ...' https://$HOST/mcp/` redirect `Location` starts with `https://`.
- [ ] Any other path (`https://$HOST/foo`) -> `404`; `http://$HOST/` -> `301` to https.
- [ ] Role privileges on the real instance:
      `psql -U fateweave_app -d fateweave -c "DELETE FROM report_versions"` -> permission denied;
      `psql -U fateweave_app -d <flight_friend_db>` -> permission denied (no cross-project access).
- [ ] Nginx access log contains no `X-Fateweave-Key` value: `grep -c <key> /var/log/nginx/fateweave.access.log` -> 0.
- [ ] **Flight Friend unaffected**: its containers' uptime/health and its public health URL unchanged before/after;
      no changes to its networks, volumes, Nginx vhost, DB or cron (`nginx -t` clean, `docker ps` diff shows only `fateweave-api`).
- [ ] Container: `docker inspect fateweave-api --format '{{.State.Health.Status}}'` -> `healthy`; port published on `127.0.0.1:8080` only (`ss -ltnp`).
- [ ] Daily backup: run `deploy/backup.sh` once manually, check file mode `600`, then
      `deploy/restore-check.sh <dump>` shows expected table counts and drops its disposable DB.
- [ ] Rollback rehearsal as documented in the README.
