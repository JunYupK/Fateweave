"""initial schema: profiles, runs, immutable report versions

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=NOW, nullable=False)


def upgrade() -> None:
    op.create_table(
        "birth_profiles",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("alias", sa.Text()),
        sa.Column("birth_input", pg.JSONB(), nullable=False),
        sa.Column("has_birth_time", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_table(
        "analysis_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("participant_ids", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False),
        sa.Column("snapshot", pg.JSONB(), nullable=False),
        sa.Column("snapshot_hash", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PREPARED"),
        sa.Column("last_validation_errors", pg.JSONB()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("mode IN ('individual','couple')", name="ck_analysis_runs_mode"),
        sa.CheckConstraint(
            "status IN ('PREPARED','VALIDATION_FAILED','FINALIZED','ABANDONED')",
            name="ck_analysis_runs_status",
        ),
    )
    op.create_index(
        "ix_analysis_runs_participant_ids",
        "analysis_runs",
        ["participant_ids"],
        postgresql_using="gin",
    )
    op.create_table(
        "report_versions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "analysis_id", pg.UUID(as_uuid=True), sa.ForeignKey("analysis_runs.id"), nullable=False
        ),
        sa.Column("idempotency_key", sa.Text()),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("report_type", sa.Text(), nullable=False),
        sa.Column("body", pg.JSONB(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("validation", pg.JSONB(), nullable=False),
        sa.Column("correction_reason", sa.Text()),
        _ts("created_at"),
        sa.CheckConstraint("version >= 1", name="ck_report_versions_version"),
        sa.UniqueConstraint("report_id", "version", name="uq_report_versions_report_version"),
        sa.UniqueConstraint(
            "analysis_id", "idempotency_key", name="uq_report_versions_analysis_idempotency"
        ),
    )
    op.create_index(
        "ix_report_versions_type_created", "report_versions", ["report_type", "created_at"]
    )
    op.create_table(
        "alternative_interpretations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("school", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence_refs", pg.JSONB(), nullable=False),
        _ts("created_at"),
        sa.ForeignKeyConstraint(
            ["report_id", "report_version"],
            ["report_versions.report_id", "report_versions.version"],
            name="fk_alternatives_report_version",
        ),
    )
    op.execute(
        """
        CREATE FUNCTION fateweave_forbid_mutation() RETURNS trigger AS $$
        BEGIN
            IF current_setting('fateweave.maintenance', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION '% on % is forbidden: records are immutable', TG_OP, TG_TABLE_NAME
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("report_versions", "alternative_interpretations"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION fateweave_forbid_mutation()"
        )


def downgrade() -> None:
    for table in ("alternative_interpretations", "report_versions"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS fateweave_forbid_mutation()")
    op.drop_table("alternative_interpretations")
    op.drop_index("ix_report_versions_type_created", table_name="report_versions")
    op.drop_table("report_versions")
    op.drop_index("ix_analysis_runs_participant_ids", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    op.drop_table("birth_profiles")
