"""The five Fateweave tools as an MCP 2.x server (MCPServer), plus Claude-facing instructions.

Service errors become tool errors whose text is "<CODE>: <message>" (those messages are already
free of birth data and report text). FinalizeResult statuses such as VALIDATION_FAILED are normal
structured results. Anything unexpected becomes a generic tool error: no traceback, no data.
"""

import logging
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Literal

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from fateweave.domain.validation import REQUIRED_SECTIONS
from fateweave.models.facts import PreparedAnalysis
from fateweave.models.inputs import BirthProfileInput
from fateweave.models.reports import ReportDraft
from fateweave.services.analysis import AnalysisError, AnalysisService
from fateweave.services.reports import (
    AlternativeView,
    FinalizeResult,
    ReportError,
    ReportService,
    ReportSummary,
    ReportView,
)

log = logging.getLogger(__name__)

SERVER_NAME = "fateweave"
PROMPT_NAME = "fateweave_report_workflow"


@dataclass
class ServiceContainer:
    analysis: AnalysisService
    reports: ReportService


def _sections(mode: str) -> str:
    return ", ".join(f"`{name}`" for name in REQUIRED_SECTIONS[mode])


WORKFLOW_KO = f"""\
Fateweave는 전통 명리(myeongri) 해석으로 결혼 사주(individual)와 커플 궁합(couple) 리포트를 \
만듭니다. 이것은 전통 해석이지 예측(prediction)이나 검증된 확률이 아닙니다.

작업 순서 (workflow):
1. `prepare_analysis`를 호출한다 (mode=`individual`은 profile 1개, `couple`은 2개). \
응답의 `analysis_id`, `facts`, `evidence_catalog`, `missing_data`만 근거로 쓴다.
2. 전체 `ReportDraft`를 작성한다 (schema_version `report-v1`).
   - individual 필수 sections: {_sections("individual")}
   - couple 필수 sections: {_sections("couple")}
   - kind `computed` claim은 `evidence_catalog`의 evidence ID(`evidence_ids`)를 인용하고, \
`computed_values`에 해당 evidence `operands`의 값을 정확히 그대로 적는다.
   - draft에는 `evidence_catalog`의 evidence ID를 인용하는 kind `computed` claim이 최소 1개 \
반드시 있어야 한다 (at least one structured computed claim citing server evidence). 없으면 \
`VALIDATION_FAILED`가 된다.
   - 해석적 판단은 kind `interpretation` claim으로 분리하고 evidence ID를 인용한다.
   - 결혼 확률·퍼센트(probability)나 O/X 판정을 절대 쓰지 않는다. 출생 시각 미상이나 \
경계(boundary) 불확실성은 limitations와 caveats에 밝힌다.
3. 새 `idempotency_key`(예: UUID)로 `finalize_report`를 호출한다. 같은 draft를 재시도할 때만 \
같은 키를 다시 쓴다.
4. 응답 `status`가 `FINALIZED`일 때에만 사용자에게 "저장되었다"고 말하고 `report_id`를 알려준다. \
그 전에는 저장되었다고 말하지 않는다.
5. `VALIDATION_FAILED`이면 `validation_errors`를 보고 draft를 고쳐 새 `idempotency_key`로 \
다시 `finalize_report`를 호출한다. `REPORT_CONFLICT`/`IDEMPOTENCY_CONFLICT`는 이미 저장된 \
리포트가 있다는 뜻이니 `get_report`/`list_reports`로 확인한다.
6. 이후 대화(follow-up)에서는 기억에 의존하지 말고 `get_report`로 저장된 리포트를 불러와 답한다. \
`list_reports`로 목록을 찾고, 다른 학파(school)의 해석은 `add_alternative_interpretation`으로 \
기준 리포트와 별도로 기록한다.
"""


def _tool_error(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)


async def _guard[T](tool: str, call: Awaitable[T]) -> T | CallToolResult:
    """Await a service call; map failures to an is_error result with exactly "<CODE>: <message>".

    Returning a CallToolResult (rather than raising ToolError, which the SDK prefixes with
    "Error executing tool <name>: ") keeps the text exact; the SDK passes it through unchanged.
    """
    try:
        return await call
    except (AnalysisError, ReportError) as exc:
        return _tool_error(f"{exc.code}: {exc.message}")
    except Exception as exc:
        log.error("tool %s failed unexpectedly: %s", tool, type(exc).__name__)
        return _tool_error("INTERNAL_ERROR: the request could not be completed")


def create_mcp_server(services: ServiceContainer) -> MCPServer:
    server = MCPServer(
        name=SERVER_NAME,
        title="Fateweave",
        instructions=WORKFLOW_KO,
    )

    @server.tool(
        title="Prepare saju analysis",
        annotations=ToolAnnotations(
            title="Prepare saju analysis",
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    async def prepare_analysis(
        mode: Literal["individual", "couple"],
        profiles: list[BirthProfileInput],
        horizon_years: int = 10,
    ) -> PreparedAnalysis:
        """Compute the chart(s) and evidence catalog; store a PREPARED snapshot (not a report).

        Call first. Write the full ReportDraft only from the returned facts/evidence_catalog.
        """
        return await _guard(
            "prepare_analysis",
            services.analysis.prepare_analysis(mode, profiles, horizon_years),
        )

    @server.tool(
        title="Finalize report",
        annotations=ToolAnnotations(
            title="Finalize report",
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def finalize_report(
        analysis_id: uuid.UUID, draft: ReportDraft, idempotency_key: str
    ) -> FinalizeResult:
        """Validate the draft against the snapshot and save it as canonical report v1.

        The report is saved only when status is FINALIZED. On VALIDATION_FAILED, fix the draft
        using validation_errors and retry with a fresh idempotency_key.
        """
        return await _guard(
            "finalize_report",
            services.reports.finalize_report(analysis_id, draft, idempotency_key),
        )

    @server.tool(
        title="Get report",
        annotations=ToolAnnotations(title="Get report", read_only_hint=True, open_world_hint=False),
    )
    async def get_report(
        report_id: uuid.UUID,
        version: int | None = None,
        format: Literal["markdown", "json"] = "markdown",
    ) -> ReportView:
        """Load a saved report (latest version by default). Use for every follow-up question."""
        return await _guard("get_report", services.reports.get_report(report_id, version, format))

    @server.tool(
        title="List reports",
        annotations=ToolAnnotations(
            title="List reports", read_only_hint=True, open_world_hint=False
        ),
    )
    async def list_reports(
        mode: Literal["individual", "couple"] | None = None, limit: int = 20
    ) -> list[ReportSummary]:
        """List saved reports, newest first (no birth data)."""
        return await _guard("list_reports", services.reports.list_reports(mode, limit))

    @server.tool(
        title="Add alternative interpretation",
        annotations=ToolAnnotations(
            title="Add alternative interpretation",
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    async def add_alternative_interpretation(
        report_id: uuid.UUID, school: str, content: str, evidence_refs: list[str]
    ) -> AlternativeView:
        """Record another school's interpretation, kept separate from the canonical report."""
        return await _guard(
            "add_alternative_interpretation",
            services.reports.add_alternative_interpretation(
                report_id, school, content, evidence_refs
            ),
        )

    @server.prompt(
        name=PROMPT_NAME,
        title="Fateweave report workflow",
        description="prepare → full draft with evidence IDs → finalize → claim saved only after "
        "FINALIZED",
    )
    def fateweave_report_workflow() -> str:
        return WORKFLOW_KO

    return server
