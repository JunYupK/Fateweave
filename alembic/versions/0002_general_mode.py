"""analysis mode general (종합 사주 리포트)

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_NAME = "ck_analysis_runs_mode"


def upgrade() -> None:
    op.drop_constraint(_NAME, "analysis_runs", type_="check")
    op.create_check_constraint(_NAME, "analysis_runs", "mode IN ('individual','couple','general')")


def downgrade() -> None:
    # Fails while general analyses exist: purge them first (they cannot be represented).
    op.drop_constraint(_NAME, "analysis_runs", type_="check")
    op.create_check_constraint(_NAME, "analysis_runs", "mode IN ('individual','couple')")
