"""Add adaptive GCSE quizzes, preparation lifecycle, variable marks, and rubrics.

Revision ID: 0010_adaptive_quizzes
Revises: 0009_account_suspension
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_adaptive_quizzes"
down_revision: str | None = "0009_account_suspension"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUPABASE_DATA_API_ROLES = ("anon", "authenticated", "service_role")


def _revoke_optional_role(table_name: str, role_name: str) -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = '{role_name}'
                ) THEN
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM %I',
                        '{table_name}',
                        '{role_name}'
                    );
                END IF;
            END $$;
            """
        )
    )


def _isolate_table(table_name: str) -> None:
    op.execute(
        sa.text(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")
    )
    op.execute(
        sa.text(f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM PUBLIC")
    )
    for role_name in _SUPABASE_DATA_API_ROLES:
        _revoke_optional_role(table_name, role_name)


def upgrade() -> None:
    # 1. Rooms extensions
    op.add_column(
        "rooms",
        sa.Column(
            "quiz_mode",
            sa.String(length=24),
            server_default=sa.text("'LEGACY_PHYSICS'"),
            nullable=False,
        ),
    )
    op.add_column(
        "rooms",
        sa.Column("education_level", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "rooms",
        sa.Column("quiz_subject", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "rooms",
        sa.Column("quiz_topic", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "rooms",
        sa.Column("target_total_marks", sa.SmallInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_rooms_quiz_mode",
        "rooms",
        "quiz_mode IN ('LEGACY_PHYSICS', 'ADAPTIVE')",
    )
    op.create_check_constraint(
        "ck_rooms_adaptive_configuration",
        "rooms",
        """
        (
            quiz_mode = 'LEGACY_PHYSICS'
            AND education_level IS NULL
            AND quiz_subject IS NULL
            AND quiz_topic IS NULL
            AND target_total_marks IS NULL
        ) OR (
            quiz_mode = 'ADAPTIVE'
            AND education_level = 'GCSE'
            AND target_total_marks BETWEEN 5 AND 40
            AND (
                (quiz_subject = 'physics' AND quiz_topic IN ('energy', 'electricity', 'forces'))
                OR (quiz_subject = 'mathematics' AND quiz_topic IN ('number', 'algebra', 'geometry'))
                OR (quiz_subject = 'biology' AND quiz_topic IN ('cells', 'organisation', 'ecology'))
                OR (quiz_subject = 'chemistry' AND quiz_topic IN ('atomic_structure', 'bonding', 'chemical_reactions'))
                OR (quiz_subject = 'english_language' AND quiz_topic IN ('reading_comprehension', 'language_analysis', 'writing_techniques'))
                OR (quiz_subject = 'english_literature' AND quiz_topic IN ('literary_devices', 'character_and_theme', 'poetry_analysis'))
            )
        )
        """,
    )

    # 2. Quiz preparations
    op.create_table(
        "quiz_preparations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'GENERATING'"),
            nullable=False,
        ),
        sa.Column(
            "state_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "generation_attempt",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_id", sa.String(length=64), nullable=False),
        sa.Column("error_category", sa.String(length=64), nullable=True),
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
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('GENERATING', 'READY', 'FAILED', 'CONSUMED', 'SUPERSEDED')",
            name="ck_quiz_preparations_status",
        ),
        sa.CheckConstraint(
            "state_version >= 1",
            name="ck_quiz_preparations_state_version",
        ),
        sa.CheckConstraint(
            "generation_attempt >= 1",
            name="ck_quiz_preparations_generation_attempt",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
            name="fk_quiz_preparations_room_id_rooms",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "room_id",
            "request_id",
            name="uq_quiz_preparations_room_request",
        ),
    )
    op.create_index(
        "uq_quiz_preparations_active_room",
        "quiz_preparations",
        ["room_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('GENERATING', 'READY')"),
    )
    op.create_index(
        "ix_quiz_preparations_room_id",
        "quiz_preparations",
        ["room_id"],
    )
    _isolate_table("quiz_preparations")

    # 3. Generated quiz questions
    op.create_table(
        "generated_quiz_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preparation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("question_type", sa.String(length=24), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("max_marks", sa.SmallInteger(), nullable=False),
        sa.Column("duration_seconds", sa.SmallInteger(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("correct_option_id", sa.String(length=64), nullable=True),
        sa.Column("grading_rubric", postgresql.JSONB(), nullable=False),
        sa.Column("worked_explanation", sa.Text(), nullable=False),
        sa.Column("original_extract", sa.Text(), nullable=True),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("position >= 0", name="ck_generated_quiz_questions_position"),
        sa.CheckConstraint(
            "question_type IN ('MULTIPLE_CHOICE', 'NUMERICAL', 'WRITTEN')",
            name="ck_generated_quiz_questions_type",
        ),
        sa.CheckConstraint(
            "max_marks BETWEEN 1 AND 6",
            name="ck_generated_quiz_questions_max_marks",
        ),
        sa.CheckConstraint(
            "duration_seconds BETWEEN 30 AND 180",
            name="ck_generated_quiz_questions_duration_seconds",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(grading_rubric) = 'object' AND length(trim(worked_explanation)) > 0",
            name="ck_generated_quiz_questions_rubric_explanation",
        ),
        sa.CheckConstraint(
            """
            (
                question_type = 'MULTIPLE_CHOICE'
                AND max_marks = 1
                AND jsonb_typeof(options) = 'array'
                AND jsonb_array_length(options) BETWEEN 2 AND 6
                AND correct_option_id IS NOT NULL
            ) OR (
                question_type IN ('NUMERICAL', 'WRITTEN')
                AND jsonb_typeof(options) = 'array'
                AND jsonb_array_length(options) = 0
                AND correct_option_id IS NULL
            )
            """,
            name="ck_generated_quiz_questions_type_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["preparation_id"],
            ["quiz_preparations.id"],
            name="fk_generated_quiz_questions_preparation_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "preparation_id",
            "position",
            name="uq_generated_quiz_questions_prep_position",
        ),
        sa.UniqueConstraint(
            "preparation_id",
            "content_fingerprint",
            name="uq_generated_quiz_questions_prep_fingerprint",
        ),
    )
    op.create_index(
        "ix_generated_quiz_questions_prep",
        "generated_quiz_questions",
        ["preparation_id"],
    )
    _isolate_table("generated_quiz_questions")

    # 4. Quiz sessions extensions
    op.add_column(
        "quiz_sessions",
        sa.Column("preparation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "quiz_sessions",
        sa.Column(
            "quiz_mode",
            sa.String(length=24),
            server_default=sa.text("'LEGACY_PHYSICS'"),
            nullable=False,
        ),
    )
    op.add_column(
        "quiz_sessions",
        sa.Column("education_level", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "quiz_sessions",
        sa.Column("quiz_subject", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "quiz_sessions",
        sa.Column("quiz_topic", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "quiz_sessions",
        sa.Column(
            "total_available_marks",
            sa.SmallInteger(),
            server_default=sa.text("5"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_quiz_sessions_preparation_id_quiz_preparations",
        "quiz_sessions",
        "quiz_preparations",
        ["preparation_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Update quiz_sessions status check constraint & active-room unique index
    op.drop_constraint("ck_quiz_sessions_status", "quiz_sessions", type_="check")
    op.create_check_constraint(
        "ck_quiz_sessions_status",
        "quiz_sessions",
        "status IN ('QUESTION_OPEN', 'QUESTION_GRADING', 'QUESTION_REVEAL', 'FINISHED')",
    )

    op.drop_index("uq_quiz_sessions_active_room", table_name="quiz_sessions")
    op.create_index(
        "uq_quiz_sessions_active_room",
        "quiz_sessions",
        ["room_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('QUESTION_OPEN', 'QUESTION_GRADING', 'QUESTION_REVEAL')"
        ),
    )

    op.create_check_constraint(
        "ck_quiz_sessions_mode_configuration",
        "quiz_sessions",
        """
        (
            quiz_mode = 'LEGACY_PHYSICS'
            AND preparation_id IS NULL
            AND education_level IS NULL
            AND quiz_subject IS NULL
            AND quiz_topic IS NULL
            AND total_available_marks = 5
        ) OR (
            quiz_mode = 'ADAPTIVE'
            AND preparation_id IS NOT NULL
            AND education_level = 'GCSE'
            AND quiz_subject IS NOT NULL
            AND quiz_topic IS NOT NULL
            AND total_available_marks BETWEEN 5 AND 40
        )
        """,
    )

    # 5. Session questions extensions
    op.alter_column(
        "session_questions",
        "source_question_id",
        nullable=True,
    )
    op.add_column(
        "session_questions",
        sa.Column("generated_question_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_session_questions_generated_question_id",
        "session_questions",
        "generated_quiz_questions",
        ["generated_question_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_session_questions_exactly_one_source",
        "session_questions",
        """
        (source_question_id IS NOT NULL AND generated_question_id IS NULL)
        OR (source_question_id IS NULL AND generated_question_id IS NOT NULL)
        """,
    )
    op.add_column(
        "session_questions",
        sa.Column(
            "question_type",
            sa.String(length=24),
            server_default=sa.text("'MULTIPLE_CHOICE'"),
            nullable=False,
        ),
    )
    op.add_column(
        "session_questions",
        sa.Column(
            "max_marks",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "session_questions",
        sa.Column(
            "grading_rubric_snapshot",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "session_questions",
        sa.Column(
            "worked_explanation_snapshot",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.add_column(
        "session_questions",
        sa.Column("original_extract", sa.Text(), nullable=True),
    )
    op.add_column(
        "session_questions",
        sa.Column(
            "content_fingerprint",
            sa.String(length=64),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.alter_column(
        "session_questions",
        "correct_option_id",
        nullable=True,
    )

    # Expand duration check to 180s
    op.drop_constraint(
        "ck_session_questions_duration_seconds",
        "session_questions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_session_questions_duration_seconds",
        "session_questions",
        "duration_seconds BETWEEN 5 AND 180",
    )
    op.create_check_constraint(
        "ck_session_questions_type_consistency",
        "session_questions",
        """
        (
            question_type = 'MULTIPLE_CHOICE'
            AND max_marks = 1
            AND correct_option_id IS NOT NULL
        ) OR (
            question_type IN ('NUMERICAL', 'WRITTEN')
            AND correct_option_id IS NULL
        )
        """,
    )

    # 6. Answer submissions extensions
    op.alter_column("answer_submissions", "selected_option_id", nullable=True)
    op.alter_column("answer_submissions", "is_correct", nullable=True)
    op.alter_column("answer_submissions", "points", nullable=True)

    op.add_column(
        "answer_submissions",
        sa.Column("answer_text", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "answer_submissions",
        sa.Column("earned_marks", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "answer_submissions",
        sa.Column(
            "grading_method",
            sa.String(length=32),
            server_default=sa.text("'LEGACY_OPTION'"),
            nullable=False,
        ),
    )
    op.add_column(
        "answer_submissions",
        sa.Column(
            "grading_status",
            sa.String(length=24),
            server_default=sa.text("'GRADED'"),
            nullable=False,
        ),
    )
    op.add_column(
        "answer_submissions",
        sa.Column(
            "attempt_cycle",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "answer_submissions",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "answer_submissions",
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "answer_submissions",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "answer_submissions",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "answer_submissions",
        sa.Column("last_error_category", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "answer_submissions",
        sa.Column(
            "awarded_criterion_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "answer_submissions",
        sa.Column(
            "feedback",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "answer_submissions",
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Backfill legacy answer submissions
    op.execute(
        sa.text(
            """
            UPDATE answer_submissions
            SET
                earned_marks = CASE WHEN is_correct = true THEN 1 ELSE 0 END,
                grading_method = 'LEGACY_OPTION',
                grading_status = 'GRADED',
                graded_at = submitted_at,
                awarded_criterion_ids = '[]'::jsonb,
                feedback = '{}'::jsonb
            WHERE grading_status = 'GRADED' AND earned_marks IS NULL
            """
        )
    )

    # Drop legacy answer submission constraints
    op.drop_constraint(
        "ck_answer_submissions_points",
        "answer_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_answer_submissions_correctness_points",
        "answer_submissions",
        type_="check",
    )

    # Add adaptive answer submission constraints
    op.create_check_constraint(
        "ck_answer_submissions_input_present",
        "answer_submissions",
        """
        (selected_option_id IS NOT NULL AND answer_text IS NULL)
        OR (selected_option_id IS NULL AND answer_text IS NOT NULL)
        """,
    )
    op.create_check_constraint(
        "ck_answer_submissions_grading_status",
        "answer_submissions",
        "grading_status IN ('PENDING', 'IN_PROGRESS', 'RETRYABLE', 'UNAVAILABLE', 'GRADED')",
    )
    op.create_check_constraint(
        "ck_answer_submissions_ungraded_nulls",
        "answer_submissions",
        """
        grading_status = 'GRADED'
        OR (is_correct IS NULL AND points IS NULL AND earned_marks IS NULL AND graded_at IS NULL
            AND awarded_criterion_ids = '[]'::jsonb AND feedback = '{}'::jsonb)
        """,
    )
    op.create_check_constraint(
        "ck_answer_submissions_feedback_json_types",
        "answer_submissions",
        """
        jsonb_typeof(awarded_criterion_ids) = 'array'
        AND jsonb_typeof(feedback) = 'object'
        """,
    )
    op.create_check_constraint(
        "ck_answer_submissions_graded_fields",
        "answer_submissions",
        """
        grading_status <> 'GRADED'
        OR (
            is_correct IS NOT NULL
            AND points IS NOT NULL
            AND earned_marks IS NOT NULL
            AND earned_marks BETWEEN 0 AND 6
            AND graded_at IS NOT NULL
        )
        """,
    )
    op.create_check_constraint(
        "ck_answer_submissions_legacy_points_invariant",
        "answer_submissions",
        "points IS NULL OR points IN (0, 100)",
    )
    op.create_check_constraint(
        "ck_answer_submissions_legacy_correctness_points",
        "answer_submissions",
        """
        points IS NULL
        OR ((is_correct AND points = 100) OR ((NOT is_correct) AND points = 0))
        """,
    )
    op.create_check_constraint(
        "ck_answer_submissions_grading_method",
        "answer_submissions",
        "grading_method IN ('LEGACY_OPTION', 'DETERMINISTIC_OPTION', 'DETERMINISTIC_NUMERICAL', 'LUNA_RUBRIC')",
    )
    op.create_index(
        "ix_answer_submissions_pending_grading",
        "answer_submissions",
        ["grading_status", "next_attempt_at"],
        postgresql_where=sa.text("grading_status IN ('PENDING', 'RETRYABLE')"),
    )


def downgrade() -> None:
    # Remove adaptive roots before narrowing any legacy duration/status checks.
    op.execute(sa.text("DELETE FROM quiz_sessions WHERE preparation_id IS NOT NULL"))
    # 6. Answer submissions downgrade
    op.drop_index(
        "ix_answer_submissions_pending_grading",
        table_name="answer_submissions",
    )
    op.drop_constraint(
        "ck_answer_submissions_feedback_json_types",
        "answer_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_answer_submissions_grading_method",
        "answer_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_answer_submissions_legacy_correctness_points",
        "answer_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_answer_submissions_legacy_points_invariant",
        "answer_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_answer_submissions_graded_fields",
        "answer_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_answer_submissions_ungraded_nulls",
        "answer_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_answer_submissions_grading_status",
        "answer_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_answer_submissions_input_present",
        "answer_submissions",
        type_="check",
    )

    # Clean up non-legacy submissions before restoring not-null / legacy constraints
    op.execute(
        sa.text(
            "DELETE FROM answer_submissions WHERE selected_option_id IS NULL OR points IS NULL"
        )
    )

    op.create_check_constraint(
        "ck_answer_submissions_points",
        "answer_submissions",
        "points IN (0, 100)",
    )
    op.create_check_constraint(
        "ck_answer_submissions_correctness_points",
        "answer_submissions",
        "(is_correct AND points = 100) OR ((NOT is_correct) AND points = 0)",
    )

    op.drop_column("answer_submissions", "graded_at")
    op.drop_column("answer_submissions", "feedback")
    op.drop_column("answer_submissions", "awarded_criterion_ids")
    op.drop_column("answer_submissions", "last_error_category")
    op.drop_column("answer_submissions", "next_attempt_at")
    op.drop_column("answer_submissions", "lease_expires_at")
    op.drop_column("answer_submissions", "claim_token")
    op.drop_column("answer_submissions", "attempt_count")
    op.drop_column("answer_submissions", "attempt_cycle")
    op.drop_column("answer_submissions", "grading_status")
    op.drop_column("answer_submissions", "grading_method")
    op.drop_column("answer_submissions", "earned_marks")
    op.drop_column("answer_submissions", "answer_text")

    op.alter_column("answer_submissions", "points", nullable=False)
    op.alter_column("answer_submissions", "is_correct", nullable=False)
    op.alter_column("answer_submissions", "selected_option_id", nullable=False)

    # 5. Session questions downgrade
    op.drop_constraint(
        "ck_session_questions_type_consistency",
        "session_questions",
        type_="check",
    )
    op.drop_constraint(
        "ck_session_questions_duration_seconds",
        "session_questions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_session_questions_duration_seconds",
        "session_questions",
        "duration_seconds BETWEEN 5 AND 120",
    )

    # Delete non-canonical session questions before restoring constraints
    op.execute(
        sa.text("DELETE FROM session_questions WHERE source_question_id IS NULL")
    )

    op.alter_column("session_questions", "correct_option_id", nullable=False)
    op.drop_column("session_questions", "content_fingerprint")
    op.drop_column("session_questions", "original_extract")
    op.drop_column("session_questions", "worked_explanation_snapshot")
    op.drop_column("session_questions", "grading_rubric_snapshot")
    op.drop_column("session_questions", "max_marks")
    op.drop_column("session_questions", "question_type")

    op.drop_constraint(
        "ck_session_questions_exactly_one_source",
        "session_questions",
        type_="check",
    )
    op.drop_constraint(
        "fk_session_questions_generated_question_id",
        "session_questions",
        type_="foreignkey",
    )
    op.drop_column("session_questions", "generated_question_id")
    op.alter_column("session_questions", "source_question_id", nullable=False)

    # 4. Quiz sessions downgrade
    op.drop_constraint(
        "ck_quiz_sessions_mode_configuration",
        "quiz_sessions",
        type_="check",
    )
    op.drop_index("uq_quiz_sessions_active_room", table_name="quiz_sessions")
    op.create_index(
        "uq_quiz_sessions_active_room",
        "quiz_sessions",
        ["room_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('QUESTION_OPEN', 'QUESTION_REVEAL')"
        ),
    )
    op.drop_constraint("ck_quiz_sessions_status", "quiz_sessions", type_="check")
    op.create_check_constraint(
        "ck_quiz_sessions_status",
        "quiz_sessions",
        "status IN ('QUESTION_OPEN', 'QUESTION_REVEAL', 'FINISHED')",
    )
    op.drop_constraint(
        "fk_quiz_sessions_preparation_id_quiz_preparations",
        "quiz_sessions",
        type_="foreignkey",
    )
    op.drop_column("quiz_sessions", "total_available_marks")
    op.drop_column("quiz_sessions", "quiz_topic")
    op.drop_column("quiz_sessions", "quiz_subject")
    op.drop_column("quiz_sessions", "education_level")
    op.drop_column("quiz_sessions", "quiz_mode")
    op.drop_column("quiz_sessions", "preparation_id")

    # 3. Generated quiz questions downgrade
    _isolate_table("generated_quiz_questions")
    op.drop_index(
        "ix_generated_quiz_questions_prep",
        table_name="generated_quiz_questions",
    )
    op.drop_table("generated_quiz_questions")

    # 2. Quiz preparations downgrade
    _isolate_table("quiz_preparations")
    op.drop_index("ix_quiz_preparations_room_id", table_name="quiz_preparations")
    op.drop_index(
        "uq_quiz_preparations_active_room",
        table_name="quiz_preparations",
    )
    op.drop_table("quiz_preparations")

    # 1. Rooms downgrade
    op.drop_constraint(
        "ck_rooms_adaptive_configuration",
        "rooms",
        type_="check",
    )
    op.drop_constraint("ck_rooms_quiz_mode", "rooms", type_="check")
    op.drop_column("rooms", "target_total_marks")
    op.drop_column("rooms", "quiz_topic")
    op.drop_column("rooms", "quiz_subject")
    op.drop_column("rooms", "education_level")
    op.drop_column("rooms", "quiz_mode")
