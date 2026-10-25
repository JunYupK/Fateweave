"""Remote MCP tools over real Streamable HTTP JSON-RPC (initialize, tools/list, tools/call)."""

import uuid
from datetime import date

from helpers import valid_draft
from mcp_http import MCPClient, running_app, services_for
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from fateweave.domain.validation import REQUIRED_SECTIONS
from fateweave.models.facts import PreparedAnalysis
from fateweave.storage.db import make_sessionmaker

FIVE_TOOLS = {
    "prepare_analysis",
    "finalize_report",
    "get_report",
    "list_reports",
    "add_alternative_interpretation",
}
PROFILE = {
    "birth_date": "1990-05-15",
    "calendar": "solar",
    "birth_time": "14:30:00",
    "gender_for_daewoon": "female",
    "longitude": 127.0,
    "alias": "me",
}


def _clock() -> date:
    return date(2026, 10, 25)


async def _prepare(client: MCPClient) -> PreparedAnalysis:
    result = await client.call_tool(
        "prepare_analysis", {"mode": "individual", "profiles": [PROFILE]}
    )
    assert result.get("isError") is not True, result
    return PreparedAnalysis.model_validate(result["structuredContent"])


async def test_tools_list_exposes_exact_five_tools():
    async with running_app() as http:
        client = MCPClient(http)
        init = await client.initialize()
        tools = (await client.request("tools/list"))["tools"]
        prompts = (await client.request("prompts/list"))["prompts"]

    by_name = {t["name"]: t for t in tools}
    assert set(by_name) == FIVE_TOOLS
    params = {name: set(t["inputSchema"]["properties"]) for name, t in by_name.items()}
    assert params == {
        "prepare_analysis": {"mode", "profiles", "horizon_years"},
        "finalize_report": {"analysis_id", "draft", "idempotency_key"},
        "get_report": {"report_id", "version", "format"},
        "list_reports": {"mode", "limit"},
        "add_alternative_interpretation": {"report_id", "school", "content", "evidence_refs"},
    }
    for t in tools:
        assert t.get("title"), t["name"]
        assert t.get("outputSchema"), t["name"]
    ann = {name: t.get("annotations") or {} for name, t in by_name.items()}
    assert ann["get_report"]["readOnlyHint"] is True
    assert ann["list_reports"]["readOnlyHint"] is True
    assert ann["finalize_report"]["idempotentHint"] is True
    assert ann["finalize_report"].get("readOnlyHint") is not True
    assert ann["prepare_analysis"].get("readOnlyHint") is not True
    assert ann["add_alternative_interpretation"].get("readOnlyHint") is not True

    instructions = init["instructions"]
    for needle in (
        "prepare_analysis",
        "finalize_report",
        "get_report",
        "FINALIZED",
        "VALIDATION_FAILED",
        "idempotency_key",
        "interpretation",
        "at least one structured computed claim citing server evidence",
    ):
        assert needle in instructions
    for section in {*REQUIRED_SECTIONS["individual"], *REQUIRED_SECTIONS["couple"]}:
        assert section in instructions
    assert [p["name"] for p in prompts] == ["fateweave_report_workflow"]


async def test_authenticated_prepare_finalize_get_end_to_end(engine: AsyncEngine):
    services = services_for(make_sessionmaker(engine), clock=_clock)
    async with running_app(services) as http:
        client = MCPClient(http)
        await client.initialize()
        prepared = await _prepare(client)
        assert prepared.status == "PREPARED"

        draft = valid_draft(prepared)
        args = {
            "analysis_id": str(prepared.analysis_id),
            "draft": draft.model_dump(mode="json"),
            "idempotency_key": "e2e-key-1",
        }
        final = await client.call_tool("finalize_report", args)
        assert final.get("isError") is not True, final
        status = final["structuredContent"]
        assert status["status"] == "FINALIZED" and status["version"] == 1
        report_id = status["report_id"]

        again = await client.call_tool("finalize_report", args)
        assert again["structuredContent"]["report_id"] == report_id  # idempotent retry

        view = (await client.call_tool("get_report", {"report_id": report_id}))["structuredContent"]
        assert view["report_id"] == report_id and view["format"] == "markdown"
        assert report_id in view["content"]
        assert "1990-05-15" not in view["content"]

        listed = (await client.call_tool("list_reports", {}))["structuredContent"]["result"]
        assert [r["report_id"] for r in listed] == [report_id]

        cue = next(e.id for e in prepared.evidence_catalog)
        alt = await client.call_tool(
            "add_alternative_interpretation",
            {
                "report_id": report_id,
                "school": "자평",
                "content": "다른 해석",
                "evidence_refs": [cue],
            },
        )
        assert alt["structuredContent"]["report_version"] == 1

        # a failed draft is a normal structured result, not a tool error
        bad = draft.model_copy(update={"sections": {}})
        failed = await client.call_tool(
            "finalize_report",
            {
                "analysis_id": str(prepared.analysis_id),
                "draft": bad.model_dump(mode="json"),
                "idempotency_key": "e2e-key-2",
            },
        )
        assert failed.get("isError") is not True
        assert failed["structuredContent"]["status"] == "VALIDATION_FAILED"
        codes = {e["code"] for e in failed["structuredContent"]["validation_errors"]}
        assert codes == {"MISSING_SECTION"}

        # service errors surface as tool errors "<CODE>: <message>"
        missing = await client.call_tool("get_report", {"report_id": str(uuid.uuid4())})
        assert missing["isError"] is True
        assert missing["content"][0]["text"] == "REPORT_NOT_FOUND: no such report or version"


async def test_stopped_after_prepare_is_not_saved(engine: AsyncEngine):
    services = services_for(make_sessionmaker(engine), clock=_clock)
    async with running_app(services) as http:
        client = MCPClient(http)
        await client.initialize()
        prepared = await _prepare(client)
        listed = (await client.call_tool("list_reports", {}))["structuredContent"]["result"]

    assert listed == []
    async with engine.connect() as conn:
        status = (
            await conn.execute(
                text("SELECT status FROM analysis_runs WHERE id = :i"),
                {"i": prepared.analysis_id},
            )
        ).scalar_one()
        reports = (await conn.execute(text("SELECT count(*) FROM report_versions"))).scalar_one()
    assert status == "PREPARED"
    assert reports == 0
