"""Add the durable server-authoritative quiz domain.

Revision ID: 0003_authoritative_quiz
Revises: 0002_supabase_identity
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_authoritative_quiz"
down_revision: str | None = "0002_supabase_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "room_memberships",
        sa.Column(
            "ready_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_room_memberships_ready_only_active",
        "room_memberships",
        "left_at IS NULL OR ready_at IS NULL",
    )

    op.create_table(
        "questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_key", sa.String(length=64), nullable=False),
        sa.Column("stable_key", sa.String(length=64), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("correct_option_id", sa.String(length=64), nullable=False),
        sa.Column("duration_seconds", sa.SmallInteger(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("position >= 0", name="ck_questions_position"),
        sa.CheckConstraint(
            "duration_seconds BETWEEN 5 AND 120",
            name="ck_questions_duration_seconds",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(options) = 'array' "
            "AND jsonb_array_length(options) BETWEEN 2 AND 6",
            name="ck_questions_options_array_length",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "bank_key",
            "stable_key",
            name="uq_questions_bank_stable_key",
        ),
        sa.UniqueConstraint(
            "bank_key",
            "position",
            name="uq_questions_bank_position",
        ),
    )
    op.create_index(
        "ix_questions_active_bank_position",
        "questions",
        ["bank_key", "is_active", "position"],
    )

    op.create_table(
        "quiz_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_bank_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "current_question_position",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "state_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "reveal_ends_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('QUESTION_OPEN', 'QUESTION_REVEAL', 'FINISHED')",
            name="ck_quiz_sessions_status",
        ),
        sa.CheckConstraint(
            "current_question_position >= 0",
            name="ck_quiz_sessions_question_position",
        ),
        sa.CheckConstraint(
            "state_version >= 1",
            name="ck_quiz_sessions_state_version",
        ),
        sa.CheckConstraint(
            "(status = 'FINISHED' AND finished_at IS NOT NULL) "
            "OR (status <> 'FINISHED' AND finished_at IS NULL)",
            name="ck_quiz_sessions_finished_at",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
            name="fk_quiz_sessions_room_id_rooms",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_quiz_sessions_active_room",
        "quiz_sessions",
        ["room_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('QUESTION_OPEN', 'QUESTION_REVEAL')"
        ),
    )
    op.create_index(
        "ix_quiz_sessions_room_started_at",
        "quiz_sessions",
        ["room_id", "started_at"],
    )

    op.create_table(
        "session_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "room_membership_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "display_name_snapshot",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["quiz_sessions.id"],
            name="fk_session_participants_session_id_quiz_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_session_participants_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["room_membership_id"],
            ["room_memberships.id"],
            name="fk_session_participants_room_membership_id_room_memberships",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "user_id",
            name="uq_session_participants_session_user",
        ),
        sa.UniqueConstraint(
            "session_id",
            "room_membership_id",
            name="uq_session_participants_session_membership",
        ),
        sa.UniqueConstraint(
            "session_id",
            "id",
            name="uq_session_participants_session_id",
        ),
    )
    op.create_index(
        "ix_session_participants_session",
        "session_participants",
        ["session_id"],
    )

    op.create_table(
        "session_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "source_question_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("prompt_snapshot", sa.Text(), nullable=False),
        sa.Column("options_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("correct_option_id", sa.String(length=64), nullable=False),
        sa.Column("duration_seconds", sa.SmallInteger(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("position >= 0", name="ck_session_questions_position"),
        sa.CheckConstraint(
            "duration_seconds BETWEEN 5 AND 120",
            name="ck_session_questions_duration_seconds",
        ),
        sa.CheckConstraint(
            "(opened_at IS NULL AND closes_at IS NULL) "
            "OR (opened_at IS NOT NULL AND closes_at IS NOT NULL "
            "AND closes_at > opened_at)",
            name="ck_session_questions_open_close_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["quiz_sessions.id"],
            name="fk_session_questions_session_id_quiz_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_question_id"],
            ["questions.id"],
            name="fk_session_questions_source_question_id_questions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "position",
            name="uq_session_questions_session_position",
        ),
        sa.UniqueConstraint(
            "session_id",
            "source_question_id",
            name="uq_session_questions_session_source",
        ),
        sa.UniqueConstraint(
            "session_id",
            "id",
            name="uq_session_questions_session_id",
        ),
    )
    op.create_index(
        "ix_session_questions_session",
        "session_questions",
        ["session_id"],
    )

    op.create_table(
        "answer_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "session_question_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("selected_option_id", sa.String(length=64), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("response_time_ms", sa.Integer(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("points", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint(
            "response_time_ms >= 0",
            name="ck_answer_submissions_response_time_ms",
        ),
        sa.CheckConstraint(
            "points IN (0, 100)",
            name="ck_answer_submissions_points",
        ),
        sa.CheckConstraint(
            "(is_correct AND points = 100) OR "
            "((NOT is_correct) AND points = 0)",
            name="ck_answer_submissions_correctness_points",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["quiz_sessions.id"],
            name="fk_answer_submissions_session_id_quiz_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "session_question_id"],
            ["session_questions.session_id", "session_questions.id"],
            name="fk_answer_submissions_session_question",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "participant_id"],
            ["session_participants.session_id", "session_participants.id"],
            name="fk_answer_submissions_session_participant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_question_id",
            "participant_id",
            name="uq_answer_submissions_question_participant",
        ),
    )
    op.create_index(
        "ix_answer_submissions_session_participant",
        "answer_submissions",
        ["session_id", "participant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_answer_submissions_session_participant",
        table_name="answer_submissions",
    )
    op.drop_table("answer_submissions")

    op.drop_index("ix_session_questions_session", table_name="session_questions")
    op.drop_table("session_questions")

    op.drop_index(
        "ix_session_participants_session",
        table_name="session_participants",
    )
    op.drop_table("session_participants")

    op.drop_index("ix_quiz_sessions_room_started_at", table_name="quiz_sessions")
    op.drop_index("uq_quiz_sessions_active_room", table_name="quiz_sessions")
    op.drop_table("quiz_sessions")

    op.drop_index("ix_questions_active_bank_position", table_name="questions")
    op.drop_table("questions")

    op.drop_constraint(
        "ck_room_memberships_ready_only_active",
        "room_memberships",
        type_="check",
    )
    op.drop_column("room_memberships", "ready_at")
