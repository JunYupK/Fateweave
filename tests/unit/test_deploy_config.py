"""Guards for the edge proxy config the Claude connector depends on (see CLAUDE.md)."""

import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CADDY = (ROOT / "deploy" / "caddy-fateweave.caddy").read_text()
COMPOSE = (ROOT / "deploy" / "compose.fateweave.yaml").read_text()


def test_caddy_forwards_the_key_in_path_route():
    match = re.search(r"@mcp path_regexp (\S+)", CADDY)
    assert match, "the Caddy block must route /mcp and /mcp/<key>"
    pattern = re.compile(match.group(1))
    key = secrets.token_urlsafe(32)  # how FATEWEAVE_MCP_KEY is generated (README, key rotation)
    assert pattern.fullmatch(f"/mcp/{key}")
    assert pattern.fullmatch("/mcp")
    for path in ("/mcp/", "/mcp/short", f"/mcp/{key}/x", "/mcpx"):
        assert not pattern.fullmatch(path), path


def test_caddy_reaches_the_container_by_name_without_access_log():
    upstreams = re.findall(r"reverse_proxy (\S+)", CADDY)
    assert upstreams and set(upstreams) == {"fateweave-api:8080"}
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}:\d+", CADDY), "no bridge IPs: use the name"
    assert not re.search(r"^\s*log\b", CADDY, re.MULTILINE), "no access log: the path is secret"


def test_compose_joins_the_edge_network():
    service_networks = re.search(r"\n    networks:\n((?:      - \S+\n)+)", COMPOSE)
    assert service_networks and "- edge" in service_networks.group(1)
    assert re.search(r"\n  edge:\n    external: true\n", COMPOSE)
    published = re.findall(r"^\s+- \"(\S+:8080:8080)\"$", COMPOSE, re.MULTILINE)
    assert published == ["127.0.0.1:8080:8080"]
