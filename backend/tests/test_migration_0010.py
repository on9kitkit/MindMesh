"""Comprehensive tests for migration 0010 (adaptive quizzes schema and isolation)."""

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.generated_quiz_question import GeneratedQuizQuestionModel
from app.db.models.membership import RoomMembershipModel
from app.db.models.quiz_preparation import QuizPreparationModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.db.models.user import UserModel
from app.db.session import Database
from app.generator.verification import VERIFICATION_REVISION
from app.repositories.postgres_users import PostgresUserRepository
from tests.conftest import OWNER_ID

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def migration_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


def test_migration_0010_upgrade_downgrade_round_trip(
    postgres_database: Database,
) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required")

    config = migration_config(database_url)

    # Downgrade to 0009
    command.downgrade(config, "0009_account_suspension")
    with postgres_database.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "quiz_preparations" not in tables
        assert "generated_quiz_questions" not in tables
        columns = {col["name"] for col in inspect(connection).get_columns("rooms")}
        assert "quiz_mode" not in columns

    # Re-upgrade to head
    command.upgrade(config, "head")
    with postgres_database.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "quiz_preparations" in tables
        assert "generated_quiz_questions" in tables
        columns = {col["name"] for col in inspect(connection).get_columns("rooms")}
        assert "quiz_mode" in columns


def test_migration_0010_rls_and_privileges_isolation(
    postgres_database: Database,
) -> None:
    for table_name in ("quiz_preparations", "generated_quiz_questions"):
        with postgres_database.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        relation.relrowsecurity,
                        (
                            SELECT count(*)
                            FROM pg_policy AS policy
                            WHERE policy.polrelid = relation.oid
                        ) AS policy_count,
                        COALESCE(
                            (
                                SELECT bool_or(acl.grantee = 0)
                                FROM aclexplode(relation.relacl) AS acl
                            ),
                            false
                        ) AS public_acl
                    FROM pg_class AS relation
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relname = :table_name
                    """
                ),
                {"table_name": table_name},
            ).one()
            assert row.relrowsecurity is True, f"RLS must be enabled on {table_name}"
            assert row.policy_count == 0, f"No RLS policies must exist on {table_name}"
            assert row.public_acl is False, f"PUBLIC privileges must be revoked from {table_name}"


def test_rooms_check_constraints_adaptive_and_legacy(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = uuid4()
    with postgres_database.session_factory() as session:
        with session.begin():
            # 1. Valid legacy room
            room = RoomModel(
                id=room_id,
                owner_id=OWNER_ID,
                name="Legacy Room",
                join_code="LEG001",
                maximum_members=8,
                quiz_mode="LEGACY_PHYSICS",
            )
            session.add(room)

    # 2. Invalid legacy room with adaptive fields populated
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory() as session:
            with session.begin():
                session.add(
                    RoomModel(
                        id=uuid4(),
                        owner_id=OWNER_ID,
                        name="Bad Legacy",
                        join_code="LEG002",
                        maximum_members=8,
                        quiz_mode="LEGACY_PHYSICS",
                        education_level="GCSE",
                    )
                )

    # 3. Valid adaptive room
    adaptive_room_id = uuid4()
    with postgres_database.session_factory() as session:
        with session.begin():
            session.add(
                RoomModel(
                    id=adaptive_room_id,
                    owner_id=OWNER_ID,
                    name="Adaptive Room",
                    join_code="ADAP01",
                    maximum_members=8,
                    quiz_mode="ADAPTIVE",
                    education_level="GCSE",
                    quiz_subject="physics",
                    quiz_topic="energy",
                    target_total_marks=20,
                )
            )

    # 4. Invalid adaptive room: wrong education level
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory() as session:
            with session.begin():
                session.add(
                    RoomModel(
                        id=uuid4(),
                        owner_id=OWNER_ID,
                        name="Bad Level",
                        join_code="ADAP02",
                        maximum_members=8,
                        quiz_mode="ADAPTIVE",
                        education_level="A-LEVEL",
                        quiz_subject="physics",
                        quiz_topic="energy",
                        target_total_marks=20,
                    )
                )

    # 5. Invalid adaptive room: subject/topic mismatch
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory() as session:
            with session.begin():
                session.add(
                    RoomModel(
                        id=uuid4(),
                        owner_id=OWNER_ID,
                        name="Bad Topic",
                        join_code="ADAP03",
                        maximum_members=8,
                        quiz_mode="ADAPTIVE",
                        education_level="GCSE",
                        quiz_subject="physics",
                        quiz_topic="algebra",  # algebra is mathematics!
                        target_total_marks=20,
                    )
                )

    # 6. Invalid adaptive room: marks outside 5-40
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory() as session:
            with session.begin():
                session.add(
                    RoomModel(
                        id=uuid4(),
                        owner_id=OWNER_ID,
                        name="Bad Marks",
                        join_code="ADAP04",
                        maximum_members=8,
                        quiz_mode="ADAPTIVE",
                        education_level="GCSE",
                        quiz_subject="physics",
                        quiz_topic="energy",
                        target_total_marks=45,
                    )
                )


def test_quiz_preparations_unique_active_room_constraint(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = uuid4()
    with postgres_database.session_factory() as session:
        with session.begin():
            session.add(
                RoomModel(
                    id=room_id,
                    owner_id=OWNER_ID,
                    name="Prep Room",
                    join_code="PREP01",
                    maximum_members=8,
                    quiz_mode="ADAPTIVE",
                    education_level="GCSE",
                    quiz_subject="physics",
                    quiz_topic="forces",
                    target_total_marks=10,
                )
            )
            session.flush()
            session.add(
                QuizPreparationModel(
                    id=uuid4(),
                    room_id=room_id,
                    request_id=uuid4(),
                    status="GENERATING",
                    model_id="gpt-5.6-luna",
                )
            )

    # Second concurrent GENERATING or READY preparation in the same room is blocked by partial unique index
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory() as session:
            with session.begin():
                session.add(
                    QuizPreparationModel(
                        id=uuid4(),
                        room_id=room_id,
                        request_id=uuid4(),
                        status="READY",
                        verification_revision=VERIFICATION_REVISION,
                        verified_content_digest="0" * 64,
                        model_id="gpt-5.6-luna",
                    )
                )


def test_generated_quiz_questions_type_consistency_checks(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = uuid4()
    prep_id = uuid4()
    with postgres_database.session_factory() as session:
        with session.begin():
            session.add(
                RoomModel(
                    id=room_id,
                    owner_id=OWNER_ID,
                    name="Gen Room",
                    join_code="GEN001",
                    maximum_members=8,
                    quiz_mode="ADAPTIVE",
                    education_level="GCSE",
                    quiz_subject="biology",
                    quiz_topic="cells",
                    target_total_marks=10,
                )
            )
            session.flush()
            session.add(
                QuizPreparationModel(
                    id=prep_id,
                    room_id=room_id,
                        request_id=uuid4(),
                        status="READY",
                        verification_revision=VERIFICATION_REVISION,
                        verified_content_digest="0" * 64,
                        model_id="gpt-5.6-luna",
                )
            )

    # Valid MCQ
    with postgres_database.session_factory() as session:
        with session.begin():
            session.add(
                GeneratedQuizQuestionModel(
                    id=uuid4(),
                    preparation_id=prep_id,
                    position=0,
                    question_type="MULTIPLE_CHOICE",
                    prompt="What is a cell?",
                    max_marks=1,
                    duration_seconds=30,
                    options=[{"id": "a", "label": "Unit"}, {"id": "b", "label": "Other"}],
                    correct_option_id="a",
                    grading_rubric={"type": "mcq"},
                    worked_explanation="A cell is the basic unit of life.",
                    content_fingerprint="fp1",
                )
            )

    # Invalid MCQ: max_marks > 1
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory() as session:
            with session.begin():
                session.add(
                    GeneratedQuizQuestionModel(
                        id=uuid4(),
                        preparation_id=prep_id,
                        position=1,
                        question_type="MULTIPLE_CHOICE",
                        prompt="Invalid MCQ",
                        max_marks=2,
                        duration_seconds=60,
                        options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                        correct_option_id="a",
                        grading_rubric={"type": "mcq"},
                        worked_explanation="Exp",
                        content_fingerprint="fp2",
                    )
                )

    # Valid WRITTEN question
    with postgres_database.session_factory() as session:
        with session.begin():
            session.add(
                GeneratedQuizQuestionModel(
                    id=uuid4(),
                    preparation_id=prep_id,
                    position=1,
                    question_type="WRITTEN",
                    prompt="Explain mitosis.",
                    max_marks=4,
                    duration_seconds=120,
                    options=[],
                    correct_option_id=None,
                    grading_rubric={"criteria": []},
                    worked_explanation="Explanation of mitosis.",
                    content_fingerprint="fp3",
                )
            )

    # Invalid WRITTEN: options populated
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory() as session:
            with session.begin():
                session.add(
                    GeneratedQuizQuestionModel(
                        id=uuid4(),
                        preparation_id=prep_id,
                        position=2,
                        question_type="WRITTEN",
                        prompt="Bad written",
                        max_marks=3,
                        duration_seconds=90,
                        options=[{"id": "opt1", "label": "No options allowed"}],
                        correct_option_id=None,
                        grading_rubric={"criteria": []},
                        worked_explanation="Exp",
                        content_fingerprint="fp4",
                    )
                )


def test_answer_submissions_grading_status_and_invariants(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = uuid4()
    prep_id = uuid4()
    gen_q_id = uuid4()
    session_id = uuid4()
    sq_id = uuid4()
    participant_id = uuid4()
    membership_id = uuid4()

    with postgres_database.session_factory() as session:
        with session.begin():
            session.add(
                RoomModel(
                    id=room_id,
                    owner_id=OWNER_ID,
                    name="Sub Room",
                    join_code="SUB001",
                    maximum_members=8,
                    quiz_mode="ADAPTIVE",
                    education_level="GCSE",
                    quiz_subject="chemistry",
                    quiz_topic="bonding",
                    target_total_marks=5,
                )
            )
            session.flush()

            session.add(
                QuizPreparationModel(
                    id=prep_id,
                    room_id=room_id,
                        request_id=uuid4(),
                        status="READY",
                        verification_revision=VERIFICATION_REVISION,
                        verified_content_digest="0" * 64,
                        model_id="gpt-5.6-luna",
                )
            )
            session.flush()

            session.add(
                GeneratedQuizQuestionModel(
                    id=gen_q_id,
                    preparation_id=prep_id,
                    position=0,
                    question_type="WRITTEN",
                    prompt="Describe ionic bonding.",
                    max_marks=5,
                    duration_seconds=150,
                    options=[],
                    correct_option_id=None,
                    grading_rubric={"criteria": []},
                    worked_explanation="Electrostatic attraction between oppositely charged ions.",
                    content_fingerprint="fp_chem",
                )
            )
            session.flush()

            session.add(
                QuizSessionModel(
                    id=session_id,
                    room_id=room_id,
                    preparation_id=prep_id,
                    question_bank_key="adaptive:prep",
                    quiz_mode="ADAPTIVE",
                    education_level="GCSE",
                    quiz_subject="chemistry",
                    quiz_topic="bonding",
                    total_available_marks=5,
                    status="QUESTION_OPEN",
                )
            )
            session.flush()

            session.add(
                SessionQuestionModel(
                    id=sq_id,
                    session_id=session_id,
                    source_question_id=None,
                    generated_question_id=gen_q_id,
                    position=0,
                    question_type="WRITTEN",
                    max_marks=5,
                    prompt_snapshot="Describe ionic bonding.",
                    options_snapshot=[],
                    correct_option_id=None,
                    grading_rubric_snapshot={"criteria": []},
                    worked_explanation_snapshot="Electrostatic attraction...",
                    content_fingerprint="fp_chem",
                    duration_seconds=150,
                )
            )
            session.add(
                RoomMembershipModel(
                    id=membership_id,
                    room_id=room_id,
                    user_id=OWNER_ID,
                )
            )
            session.flush()

            session.add(
                SessionParticipantModel(
                    id=participant_id,
                    session_id=session_id,
                    user_id=OWNER_ID,
                    room_membership_id=membership_id,
                    display_name_snapshot="Tester",
                )
            )

    # 1. Valid PENDING submission for written answer (ungraded nulls satisfied)
    with postgres_database.session_factory() as session:
        with session.begin():
            session.add(
                AnswerSubmissionModel(
                    id=uuid4(),
                    session_id=session_id,
                    session_question_id=sq_id,
                    participant_id=participant_id,
                    selected_option_id=None,
                    answer_text="Electrons are transferred from metal to non-metal.",
                    response_time_ms=12000,
                    grading_method="LUNA_RUBRIC",
                    grading_status="PENDING",
                    is_correct=None,
                    points=None,
                    earned_marks=None,
                    graded_at=None,
                )
            )

    # 2. Invalid submission: both selected_option_id and answer_text present
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory() as session:
            with session.begin():
                session.add(
                    AnswerSubmissionModel(
                        id=uuid4(),
                        session_id=session_id,
                        session_question_id=sq_id,
                        participant_id=participant_id,
                        selected_option_id="opt_a",
                        answer_text="Some text",
                        response_time_ms=1000,
                    )
                )


def test_cascade_and_restrict_delete_behaviors(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    room_id = uuid4()
    prep_id = uuid4()
    gen_q_id = uuid4()

    with postgres_database.session_factory() as session:
        with session.begin():
            session.add(
                RoomModel(
                    id=room_id,
                    owner_id=OWNER_ID,
                    name="Cascade Room",
                    join_code="CAS001",
                    maximum_members=8,
                    quiz_mode="ADAPTIVE",
                    education_level="GCSE",
                    quiz_subject="physics",
                    quiz_topic="forces",
                    target_total_marks=10,
                )
            )
            session.flush()
            session.add(
                QuizPreparationModel(
                    id=prep_id,
                    room_id=room_id,
                        request_id=uuid4(),
                        status="READY",
                        verification_revision=VERIFICATION_REVISION,
                        verified_content_digest="0" * 64,
                        model_id="gpt-5.6-luna",
                )
            )
            session.flush()
            session.add(
                GeneratedQuizQuestionModel(
                    id=gen_q_id,
                    preparation_id=prep_id,
                    position=0,
                    question_type="NUMERICAL",
                    prompt="Calculate force.",
                    max_marks=2,
                    duration_seconds=60,
                    options=[],
                    correct_option_id=None,
                    grading_rubric={"expected_value": "10"},
                    worked_explanation="F = ma",
                    content_fingerprint="fp_force",
                )
            )

    # Deleting the room cascades to quiz_preparations and generated_quiz_questions
    with postgres_database.session_factory() as session:
        with session.begin():
            room = session.get(RoomModel, room_id)
            assert room is not None
            session.delete(room)

    with postgres_database.session_factory() as session:
        prep = session.get(QuizPreparationModel, prep_id)
        assert prep is None
        gen_q = session.get(GeneratedQuizQuestionModel, gen_q_id)
        assert gen_q is None


def test_migration_0010_downgrade_with_populated_adaptive_graph(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    """Downgrade executes with live adaptive rows and leaves no feature orphans."""
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required")
    config = migration_config(database_url)

    room_id = uuid4()
    legacy_room_id = uuid4()
    prep_id = uuid4()
    gen_mcq_id = uuid4()
    gen_num_id = uuid4()
    gen_written_id = uuid4()
    session_id = uuid4()
    sq_mcq_id = uuid4()
    sq_num_id = uuid4()
    sq_written_id = uuid4()
    membership_id = uuid4()
    participant_id = uuid4()
    now = datetime.now(timezone.utc)

    with postgres_database.session_factory() as session:
        with session.begin():
            # Legacy room must survive the downgrade untouched.
            session.add(
                RoomModel(
                    id=legacy_room_id,
                    owner_id=OWNER_ID,
                    name="Legacy Survivor",
                    join_code="LEG9DG",
                    maximum_members=8,
                    quiz_mode="LEGACY_PHYSICS",
                )
            )
            # Adaptive room using snake_case identifiers end to end.
            session.add(
                RoomModel(
                    id=room_id,
                    owner_id=OWNER_ID,
                    name="Adaptive Downgrade",
                    join_code="ADPDG1",
                    maximum_members=8,
                    quiz_mode="ADAPTIVE",
                    education_level="GCSE",
                    quiz_subject="english_literature",
                    quiz_topic="character_and_theme",
                    target_total_marks=9,
                )
            )
            session.flush()
            session.add(
                QuizPreparationModel(
                    id=prep_id,
                    room_id=room_id,
                        request_id=uuid4(),
                        status="READY",
                        verification_revision=VERIFICATION_REVISION,
                        verified_content_digest="0" * 64,
                        model_id="gpt-5.6-luna",
                )
            )
            session.flush()
            for gen_id, position, qtype, prompt, marks, duration, options, correct, rubric, fp in (
                (
                    gen_mcq_id, 0, "MULTIPLE_CHOICE", "Pick the device.",
                    1, 30,
                    [{"id": "opt_a", "label": "Metaphor"}, {"id": "opt_b", "label": "Spoon"}],
                    "opt_a", {"type": "mcq"}, "fp_dg_mcq",
                ),
                (
                    gen_num_id, 1, "NUMERICAL", "Count the syllables.",
                    2, 60, [], None,
                    {"expected_value": "10"}, "fp_dg_num",
                ),
                (
                    gen_written_id, 2, "WRITTEN", "Discuss the theme.",
                    6, 180, [], None,
                    {"criteria": []}, "fp_dg_written",
                ),
            ):
                session.add(
                    GeneratedQuizQuestionModel(
                        id=gen_id,
                        preparation_id=prep_id,
                        position=position,
                        question_type=qtype,
                        prompt=prompt,
                        max_marks=marks,
                        duration_seconds=duration,
                        options=options,
                        correct_option_id=correct,
                        grading_rubric=rubric,
                        worked_explanation="Worked explanation.",
                        content_fingerprint=fp,
                    )
                )
            session.flush()
            # GRADING-status session: the legacy status check forbids this
            # value, so downgrade must remove the adaptive session itself.
            session.add(
                QuizSessionModel(
                    id=session_id,
                    room_id=room_id,
                    preparation_id=prep_id,
                    question_bank_key=f"adaptive:{prep_id}",
                    quiz_mode="ADAPTIVE",
                    education_level="GCSE",
                    quiz_subject="english_literature",
                    quiz_topic="character_and_theme",
                    total_available_marks=9,
                    status="QUESTION_GRADING",
                    current_question_position=2,
                )
            )
            session.flush()
            for sq_id, gen_id, position, qtype, marks, correct in (
                (sq_mcq_id, gen_mcq_id, 0, "MULTIPLE_CHOICE", 1, "opt_a"),
                (sq_num_id, gen_num_id, 1, "NUMERICAL", 2, None),
                (sq_written_id, gen_written_id, 2, "WRITTEN", 6, None),
            ):
                session.add(
                    SessionQuestionModel(
                        id=sq_id,
                        session_id=session_id,
                        source_question_id=None,
                        generated_question_id=gen_id,
                        position=position,
                        question_type=qtype,
                        max_marks=marks,
                        prompt_snapshot=f"Snapshot {position}.",
                        options_snapshot=(
                            [{"id": "opt_a", "label": "Metaphor"}, {"id": "opt_b", "label": "Spoon"}]
                            if qtype == "MULTIPLE_CHOICE"
                            else []
                        ),
                        correct_option_id=correct,
                        grading_rubric_snapshot={"criteria": []},
                        worked_explanation_snapshot="Worked explanation.",
                        content_fingerprint=f"fp_dg_sq{position}",
                        duration_seconds=30 * marks,
                    )
                )
            session.add(
                RoomMembershipModel(
                    id=membership_id,
                    room_id=room_id,
                    user_id=OWNER_ID,
                )
            )
            session.flush()
            session.add(
                SessionParticipantModel(
                    id=participant_id,
                    session_id=session_id,
                    user_id=OWNER_ID,
                    room_membership_id=membership_id,
                    display_name_snapshot="Tester",
                )
            )
            session.flush()
            # One graded MCQ choice, one graded numerical text, one PENDING
            # written text: exercises every submissions cleanup branch.
            session.add(
                AnswerSubmissionModel(
                    id=uuid4(),
                    session_id=session_id,
                    session_question_id=sq_mcq_id,
                    participant_id=participant_id,
                    selected_option_id="opt_a",
                    answer_text=None,
                    response_time_ms=1500,
                    grading_method="DETERMINISTIC_OPTION",
                    grading_status="GRADED",
                    is_correct=True,
                    points=100,
                    earned_marks=1,
                    graded_at=now,
                )
            )
            session.add(
                AnswerSubmissionModel(
                    id=uuid4(),
                    session_id=session_id,
                    session_question_id=sq_num_id,
                    participant_id=participant_id,
                    selected_option_id=None,
                    answer_text="10",
                    response_time_ms=4000,
                    grading_method="DETERMINISTIC_NUMERICAL",
                    grading_status="GRADED",
                    is_correct=True,
                    points=100,
                    earned_marks=2,
                    graded_at=now,
                )
            )
            session.add(
                AnswerSubmissionModel(
                    id=uuid4(),
                    session_id=session_id,
                    session_question_id=sq_written_id,
                    participant_id=participant_id,
                    selected_option_id=None,
                    answer_text="The theme develops through contrast.",
                    response_time_ms=20000,
                    grading_method="LUNA_RUBRIC",
                    grading_status="PENDING",
                    is_correct=None,
                    points=None,
                    earned_marks=None,
                    graded_at=None,
                )
            )

    # Downgrade must execute without FK failures.
    command.downgrade(config, "0009_account_suspension")

    with postgres_database.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "quiz_preparations" not in tables
        assert "generated_quiz_questions" not in tables
        room_columns = {col["name"] for col in inspect(connection).get_columns("rooms")}
        assert "quiz_mode" not in room_columns
        assert "quiz_subject" not in room_columns
        # No orphaned feature rows survive in shared tables.
        assert connection.execute(
            text("SELECT COUNT(*) FROM session_questions WHERE source_question_id IS NULL")
        ).scalar() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM answer_submissions WHERE selected_option_id IS NULL")
        ).scalar() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM quiz_sessions WHERE status = 'QUESTION_GRADING'")
        ).scalar() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM quiz_sessions WHERE room_id = :room_id"),
            {"room_id": str(room_id)},
        ).scalar() == 0
        # Legacy room survives untouched.
        assert connection.execute(
            text("SELECT COUNT(*) FROM rooms WHERE id = :room_id"),
            {"room_id": str(legacy_room_id)},
        ).scalar() == 1

    # Re-upgrade restores the feature contract.
    command.upgrade(config, "head")
    with postgres_database.engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert "quiz_preparations" in tables
        assert "generated_quiz_questions" in tables
        room_columns = {col["name"] for col in inspect(connection).get_columns("rooms")}
        assert "quiz_mode" in room_columns
