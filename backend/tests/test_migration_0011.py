"""Database-backed proofs for the content-verification gate migration and CAS."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect, text

from app.db.session import Database
from app.domain.member import RoomMember
from app.domain.room import Room
from app.generator.protocol import GenerationRequest
from app.generator.verification import (
    FakeQuizContentVerifier,
    VERIFICATION_REVISION,
    VerifiedQuizSet,
    compute_verified_content_digest,
    make_sample_consistent_quiz_set,
)
from app.repositories.postgres_quiz_preparations import (
    PostgresQuizPreparationRepository,
)
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from tests.conftest import OWNER_ID

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _migration_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


def _seed_pre_gate_rows(database: Database) -> tuple[UUID, UUID, UUID]:
    """Seed one READY, GENERATING, and CONSUMED row while at revision 0010."""
    room_ids = (uuid4(), uuid4(), uuid4())
    preparation_ids = (uuid4(), uuid4(), uuid4())
    now = datetime.now(timezone.utc)
    with database.engine.begin() as connection:
        for index, room_id in enumerate(room_ids):
            connection.execute(
                text(
                    """
                    INSERT INTO rooms (
                        id, owner_id, name, join_code, maximum_members,
                        quiz_mode, education_level, quiz_subject, quiz_topic,
                        target_total_marks
                    ) VALUES (
                        :id, :owner_id, :name, :join_code, 8,
                        'ADAPTIVE', 'GCSE', 'mathematics', 'algebra', 5
                    )
                    """
                ),
                {
                    "id": room_id,
                    "owner_id": OWNER_ID,
                    "name": f"Gate migration {index}",
                    "join_code": f"G{index:05d}",
                },
            )

        states = ("READY", "GENERATING", "CONSUMED")
        for index, status in enumerate(states):
            connection.execute(
                text(
                    """
                    INSERT INTO quiz_preparations (
                        id, room_id, request_id, status, state_version,
                        generation_attempt, claim_token, lease_expires_at,
                        model_id, created_at, updated_at, ready_at, consumed_at
                    ) VALUES (
                        :id, :room_id, :request_id, :status, :state_version,
                        1, :claim_token, :lease_expires_at, 'gpt-5.6-luna',
                        :created_at, :updated_at, :ready_at, :consumed_at
                    )
                    """
                ),
                {
                    "id": preparation_ids[index],
                    "room_id": room_ids[index],
                    "request_id": uuid4(),
                    "status": status,
                    "state_version": index + 3,
                    "claim_token": uuid4() if status != "CONSUMED" else None,
                    "lease_expires_at": now + timedelta(minutes=5)
                    if status != "CONSUMED"
                    else None,
                    "created_at": now,
                    "updated_at": now,
                    "ready_at": now if status == "READY" else None,
                    "consumed_at": now if status == "CONSUMED" else None,
                },
            )

        # Generated definitions are historical data and must survive the gate
        # invalidation and a 0011 downgrade.
        for preparation_id in (preparation_ids[0], preparation_ids[2]):
            connection.execute(
                text(
                    """
                    INSERT INTO generated_quiz_questions (
                        id, preparation_id, position, question_type, prompt,
                        max_marks, duration_seconds, options, correct_option_id,
                        grading_rubric, worked_explanation, content_fingerprint,
                        created_at
                    ) VALUES (
                        :id, :preparation_id, 0, 'MULTIPLE_CHOICE',
                        'Historical question', 1, 30,
                        CAST(:options AS jsonb), 'a', CAST(:rubric AS jsonb),
                        'Historical explanation', :fingerprint, :created_at
                    )
                    """
                ),
                {
                    "id": uuid4(),
                    "preparation_id": preparation_id,
                    "options": json.dumps(
                        [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]
                    ),
                    "rubric": json.dumps({}),
                    "fingerprint": uuid4().hex + uuid4().hex,
                    "created_at": now,
                },
            )
    return preparation_ids


def test_migration_0011_invalidates_only_pre_gate_active_rows_and_downgrades_cleanly(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    """0011 invalidates active rows, preserves history, and drops only proof fields."""
    database_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required")
    config = _migration_config(database_url)

    command.downgrade(config, "0010_adaptive_quizzes")
    preparation_ids = _seed_pre_gate_rows(postgres_database)
    command.upgrade(config, "head")

    with postgres_database.engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT id, status, state_version, error_category,
                       claim_token, lease_expires_at, ready_at
                FROM quiz_preparations
                WHERE id IN (:ready_id, :generating_id, :consumed_id)
                ORDER BY id
                """
            ),
            {
                "ready_id": preparation_ids[0],
                "generating_id": preparation_ids[1],
                "consumed_id": preparation_ids[2],
            },
        ).all()
        by_id = {row.id: row for row in rows}
        for index in (0, 1):
            row = by_id[preparation_ids[index]]
            assert row.status == "FAILED"
            assert row.error_category == "verification_required"
            assert row.state_version == index + 4
            assert row.claim_token is None
            assert row.lease_expires_at is None
            assert row.ready_at is None

        consumed = by_id[preparation_ids[2]]
        assert consumed.status == "CONSUMED"
        assert consumed.state_version == 5
        assert connection.execute(
            text(
                "SELECT count(*) FROM generated_quiz_questions "
                "WHERE preparation_id IN (:ready_id, :consumed_id)"
            ),
            {"ready_id": preparation_ids[0], "consumed_id": preparation_ids[2]},
        ).scalar_one() == 2

        columns = {column["name"] for column in inspect(connection).get_columns("quiz_preparations")}
        assert {"verification_revision", "verified_content_digest"}.issubset(columns)

    command.downgrade(config, "0010_adaptive_quizzes")
    with postgres_database.engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("quiz_preparations")}
        assert "verification_revision" not in columns
        assert "verified_content_digest" not in columns
        assert connection.execute(
            text(
                "SELECT count(*) FROM generated_quiz_questions "
                "WHERE preparation_id IN (:ready_id, :consumed_id)"
            ),
            {"ready_id": preparation_ids[0], "consumed_id": preparation_ids[2]},
        ).scalar_one() == 2
    command.upgrade(config, "head")


def _verified_sample_set() -> VerifiedQuizSet:
    questions = make_sample_consistent_quiz_set()
    request = GenerationRequest(
        education_level="GCSE",
        quiz_subject="mathematics",
        quiz_topic="algebra",
        target_total_marks=5,
    )
    return asyncio.run(FakeQuizContentVerifier().verify_quiz_content(questions, request))


def _create_room_and_claim(
    database: Database,
    suffix: str,
    owner_id: UUID = OWNER_ID,
):
    users = PostgresUserRepository(database.session_factory)
    users.upsert_profile(owner_id, "Room Owner")
    room = Room(
        id=uuid4(),
        owner_id=owner_id,
        name=f"CAS {suffix}",
        join_code=f"C{suffix:0>5}"[-6:],
        maximum_members=8,
        quiz_mode="ADAPTIVE",
        education_level="GCSE",
        quiz_subject="mathematics",
        quiz_topic="algebra",
        target_total_marks=5,
    )
    rooms = PostgresRoomRepository(database.session_factory)
    rooms.create_with_owner(room, RoomMember(room_id=room.id, user_id=owner_id, display_name="Owner"))
    preparations = PostgresQuizPreparationRepository(database.session_factory)
    preparation, claimed = preparations.claim_or_create_preparation(
        room.id, uuid4(), VERIFICATION_REVISION
    )
    assert claimed
    return rooms, preparations, room, preparation


def test_0011_final_cas_rejects_tampered_typed_proof_and_closed_room(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    """Malformed proof payloads and a close-before-commit can never create READY."""
    rooms, preparations, room, preparation = _create_room_and_claim(postgres_database, "bad")
    verified = _verified_sample_set()
    tampered_question = replace(verified.candidate_questions[0], duration_seconds=999)
    tampered = VerifiedQuizSet(
        candidate_questions=(tampered_question, *verified.candidate_questions[1:]),
        verdicts=verified.verdicts,
        verification_revision=verified.verification_revision,
        verified_content_digest=compute_verified_content_digest(
            (tampered_question, *verified.candidate_questions[1:]),
            VERIFICATION_REVISION,
        ),
    )

    with pytest.raises(ValueError, match="local validation"):
        preparations.store_generated_questions_cas(
            preparation.id,
            preparation.request_id,
            preparation.claim_token,
            preparation.generation_attempt,
            tampered,
            operation_deadline=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
    after_tamper = preparations.get_by_id(preparation.id)
    assert after_tamper is not None and after_tamper.is_generating
    assert after_tamper.questions == ()

    closed_owner_id = uuid4()
    closed_rooms, closed_preparations, closed_room, closed_preparation = _create_room_and_claim(
        postgres_database, "close", owner_id=closed_owner_id
    )
    assert not closed_rooms.close_room(closed_room.id, closed_owner_id).already_closed
    assert (
        closed_preparations.store_generated_questions_cas(
            closed_preparation.id,
            closed_preparation.request_id,
            closed_preparation.claim_token,
            closed_preparation.generation_attempt,
            verified,
            operation_deadline=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        is False
    )
    after_close = closed_preparations.get_by_id(closed_preparation.id)
    assert after_close is not None and after_close.is_generating
    assert after_close.questions == ()
