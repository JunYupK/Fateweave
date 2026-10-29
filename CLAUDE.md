# Fateweave — notes for anyone (human or agent) changing this repo

## Connector authentication: the key is in the URL path (do not remove)

The Claude custom connector cannot send custom headers, so it connects with
`https://fateweave.flight-friend.com/mcp/<FATEWEAVE_MCP_KEY>`. The server accepts the key either
as that last path segment or in the `X-Fateweave-Key` header (`src/fateweave/mcp/auth.py`).

- Keep the `/mcp/{key}` route (`src/fateweave/api.py`) and the key-in-path branch of
  `MCPKeyAuthMiddleware`. Without them the connector gets 401/404 and Claude asks for a login
  (OAuth), which this server does not offer.
- Contract tests: `test_key_in_path_authorizes_without_header` and
  `test_wrong_key_in_path_is_plain_404` (`tests/integration/test_security.py`).
- Every deploy initializes MCP through the public domain with the key in the path
  (`check_connector_url` in `deploy/deploy.sh`) and fails if it does not answer 200.
- The key is a secret: never put it (or the connector URL) in code, tests, logs, commits, PRs,
  issues or chat. It lives only in `/etc/fateweave/fateweave.env` on the VM (`FATEWEAVE_MCP_KEY`)
  and in the Claude connector settings. Read it on the VM with
  `sudo grep '^FATEWEAVE_MCP_KEY=' /etc/fateweave/fateweave.env | cut -d= -f2-`.
- Logs scrub any `/mcp/<segment>`; the edge proxy keeps no access log for the domain.

## Deploys and the VM

- The VM runs whatever `deploy/deploy.sh` checks out from `origin/master` (CI, then the Deploy
  workflow). Never commit on the VM: `deploy.sh` refuses a checkout with local edits or commits
  that are not on `origin/master`. Changes go through a PR.
- Public path: flight-friend's Caddy (`my-flight-friend-caddy-1`) → `fateweave-api:8080` on the
  `my-flight-friend_frontend` network. The site block's source of truth is
  `deploy/caddy-fateweave.caddy`; it must forward `/mcp/<key>`. Do not attach networks by hand.
- The MCP transport is stateless (`stateless_http=True`): restarts must not break connectors.
