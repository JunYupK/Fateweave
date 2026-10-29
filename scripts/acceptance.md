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
- [ ] Key-in-path: `tools/list` via `https://$HOST/mcp/<key>` without the header lists the tools; `/mcp/<wrong>` -> `404`
      (no 3xx, no `Location`); the proxy access log does not contain the key.
- [ ] Exact `/mcp` path, no redirects: `curl -sS -o /dev/null -w '%{http_code} %{redirect_url}\n' -H 'X-Fateweave-Key: ...' -X POST https://$HOST/mcp/`
      -> `404` with an empty redirect URL (no 3xx, no `Location`); the same for `/mcp/mcp` and `/mcpfoo` -> `404`.
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

## C. Claude 일반 채팅 실제 인수 - pending manual (R4)

상태: **pending manual (R4)** - 구현자는 실제 Claude 계정/OCI 배포에 접근할 수 없어 아래를 실행하지 않았다.
결정적 비-LLM 경로만 `tests/integration/test_e2e_flow.py`가 검증한다. 모든 항목은 사람이 직접 확인하기 전까지
체크하지 않는다. 실제 생년월일/리포트를 저장소·CI·이슈에 붙여넣지 말 것.

- [ ] **커넥터 등록**: Claude 설정의 Connectors에서 custom remote connector 추가. 이름 `Fateweave`,
      URL `https://<actual-host>/mcp/<key>` (Claude 커넥터는 임의 헤더를 지원하지 않으므로 키를 경로에 넣는다. 값은 서버
      시크릿 파일의 키이며, 이 URL 자체가 비밀이므로 채팅/히스토리에 노출 금지). 헤더를 지원하는 클라이언트는
      URL `https://<actual-host>/mcp` + 고정 요청 헤더 `X-Fateweave-Key`.
- [ ] **대화별 활성화**: 새 대화에서 Fateweave 도구를 활성화하고 다섯 도구가 보이는지 확인.
- [ ] **개인 케이스 1건 이상**: 개인 결혼 사주 분석 요청 -> `prepare_analysis` -> `finalize_report` 순서로 호출되는지 확인.
- [ ] **커플 케이스 1건 이상**: 커플 궁합(결혼 궁합 / 관계 잠재력 / 공통 유리 시기 3영역) 요청 -> 동일 흐름 확인.
- [ ] **저장 주장 시점**: Claude가 "저장했다"고 말하는 것은 `finalize_report`가 `FINALIZED`를 반환한 뒤에만 이루어진다.
      `VALIDATION_FAILED`/오류/미호출 시에는 저장 성공을 주장하지 않고 수정 후 재제출하거나 미저장을 밝힌다.
- [ ] **저장 검증**: Claude가 알려준 `report_id`/`version`으로 `get_report`를 호출해 같은 값과 `available_versions`가 나오는지 확인.
- [ ] **출생시간 미상 케이스**(선택): 시주가 확정되지 않고 `missing_data`에 한계가 표시되는지 확인.
- [ ] **ChatGPT handoff**: `get_report(format='markdown')` 결과 전체를 별도 ChatGPT 대화에 붙여넣고,
      "부록의 어떤 근거 ID가 이 결론을 뒷받침하는가?" 같은 근거 기반 후속 질문을 하여 답이 부록의 근거 ID를 인용하는지 확인.
      ChatGPT는 리포트에 없는 계산을 새로 만들어내서는 안 된다.
