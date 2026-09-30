"""Add content verification gate columns, constraint, and pre-gate invalidation.

Revision ID: 0011_content_verification_gate
Revises: 0010_adaptive_quizzes
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0011_content_verification_gate"
down_revision: str | None = "0010_adaptive_quizzes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add verification revision and digest columns
    op.add_column(
        "quiz_preparations",
        sa.Column("verification_revision", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "quiz_preparations",
        sa.Column("verified_content_digest", sa.String(length=64), nullable=True),
    )

    # 2. Invalidate pre-gate READY and GENERATING preparations to FAILED/verification_required.
    # Preserve generated question rows, CONSUMED rows, and completed quiz history.
    op.execute(
        sa.text(
            """
            UPDATE quiz_preparations
            SET status = 'FAILED',
                error_category = 'verification_required',
                state_version = state_version + 1,
                claim_token = NULL,
                lease_expires_at = NULL,
                ready_at = NULL,
                updated_at = NOW()
            WHERE status IN ('READY', 'GENERATING')
            """
        )
    )

    # 3. Create check constraint requiring verification fields on all READY preparations
    op.create_check_constraint(
        "ck_quiz_preparations_verification_proof",
        "quiz_preparations",
        "(status != 'READY') OR (verification_revision IS NOT NULL AND verified_content_digest IS NOT NULL)",
    )


def downgrade() -> None:
    # 1. Drop the verification proof constraint
    op.drop_constraint(
        "ck_quiz_preparations_verification_proof",
        "quiz_preparations",
        type_="check",
    )

    # 2. Drop verification revision and digest columns
    op.drop_column("quiz_preparations", "verified_content_digest")
    op.drop_column("quiz_preparations", "verification_revision")
