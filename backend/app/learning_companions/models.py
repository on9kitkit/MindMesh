"""Additive PostgreSQL models for solo study and earned cosmetic rewards.

These models are deliberately not registered through the existing model-export
module in this foundation slice. The integrator owns shared metadata wiring.
Completion receipts have NO foreign keys to users, rooms, solo attempts or
source sessions: source completion inserts them without acquiring a user FK
lock after its session lock. Deletion must remove them explicitly.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


_SUBJECT_TOPIC_CHECK = """
    (subject = 'physics' AND topic IN ('energy', 'electricity', 'forces'))
    OR (subject = 'mathematics' AND topic IN ('number', 'algebra', 'geometry'))
    OR (subject = 'biology' AND topic IN ('cells', 'organisation', 'ecology'))
    OR (subject = 'chemistry' AND topic IN
        ('atomic_structure', 'bonding', 'chemical_reactions'))
    OR (subject = 'english_language' AND topic IN
        ('reading_comprehension', 'language_analysis', 'writing_techniques'))
    OR (subject = 'english_literature' AND topic IN
        ('literary_devices', 'character_and_theme', 'poetry_analysis'))
"""

_CATALOG_IDS = (
    "'pet.owl', 'pet.tortoise', 'pet.fox', "
    "'cosmetic.study_scarf', 'animation.earned_celebration'"
)


class LearningSettingsModel(Base):
    __tablename__ = "learning_settings"
    __table_args__ = (
        CheckConstraint("home_zone_version >= 1", name="ck_learning_settings_zone_version"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    home_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    home_zone_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    zone_selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_invited_study_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_dismissed_study_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SoloAttemptModel(Base):
    __tablename__ = "solo_attempts"
    __table_args__ = (
        UniqueConstraint("owner_id", "request_id", name="uq_solo_attempts_owner_request"),
        CheckConstraint(
            "status IN ('PREPARING', 'READY', 'IN_PROGRESS', 'AWAITING_MARKING', 'FINISHED', 'ABANDONED', 'FAILED')",
            name="ck_solo_attempts_status",
        ),
        CheckConstraint(_SUBJECT_TOPIC_CHECK, name="ck_solo_attempts_subject_topic"),
        CheckConstraint("total_marks BETWEEN 5 AND 40", name="ck_solo_attempts_total_marks"),
        CheckConstraint("education_level = 'GCSE'", name="ck_solo_attempts_education_level"),
        CheckConstraint("current_question_position >= 0", name="ck_solo_attempts_question_position"),
        CheckConstraint("state_version >= 1", name="ck_solo_attempts_state_version"),
        CheckConstraint("home_zone_version >= 1", name="ck_solo_attempts_zone_version"),
        CheckConstraint(
            "(status IN ('FINISHED', 'ABANDONED', 'FAILED') AND terminal_at IS NOT NULL) "
            "OR (status NOT IN ('FINISHED', 'ABANDONED', 'FAILED') AND terminal_at IS NULL)",
            name="ck_solo_attempts_terminal_at",
        ),
        Index(
            "uq_solo_attempts_active_owner",
            "owner_id",
            unique=True,
            postgresql_where=text(
                "status IN ('PREPARING', 'READY', 'IN_PROGRESS', 'AWAITING_MARKING')"
            ),
        ),
        Index("ix_solo_attempts_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'PREPARING'"))
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    education_level: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'GCSE'"))
    subject: Mapped[str] = mapped_column(String(32), nullable=False)
    topic: Mapped[str] = mapped_column(String(40), nullable=False)
    total_marks: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    current_question_position: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    home_timezone_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    home_zone_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reward_rule_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SoloPreparationModel(Base):
    __tablename__ = "solo_preparations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('GENERATING', 'READY', 'FAILED', 'CONSUMED')",
            name="ck_solo_preparations_status",
        ),
        CheckConstraint("state_version >= 1", name="ck_solo_preparations_state_version"),
        CheckConstraint("generation_attempt >= 1", name="ck_solo_preparations_attempt"),
        CheckConstraint(
            "status NOT IN ('READY', 'CONSUMED') OR "
            "(verification_revision IS NOT NULL AND verified_content_digest IS NOT NULL)",
            name="ck_solo_preparations_verified_proof",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("solo_attempts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default=text("'GENERATING'"))
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    generation_attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    claim_token: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_content_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SoloQuestionModel(Base):
    """Prepared rows become immutable canonical snapshots when start consumes proof."""

    __tablename__ = "solo_questions"
    __table_args__ = (
        UniqueConstraint("attempt_id", "position", name="uq_solo_questions_attempt_position"),
        UniqueConstraint("attempt_id", "id", name="uq_solo_questions_attempt_id"),
        UniqueConstraint("attempt_id", "content_fingerprint", name="uq_solo_questions_attempt_fingerprint"),
        CheckConstraint("position >= 0", name="ck_solo_questions_position"),
        CheckConstraint("max_marks BETWEEN 1 AND 6", name="ck_solo_questions_max_marks"),
        CheckConstraint("question_type IN ('MULTIPLE_CHOICE', 'NUMERICAL', 'WRITTEN')", name="ck_solo_questions_type"),
        CheckConstraint("jsonb_typeof(options_snapshot) = 'array'", name="ck_solo_questions_options_array"),
        CheckConstraint("jsonb_typeof(grading_rubric_snapshot) = 'object'", name="ck_solo_questions_rubric_object"),
        CheckConstraint(
            "(question_type = 'MULTIPLE_CHOICE' AND max_marks = 1 "
            "AND jsonb_array_length(options_snapshot) BETWEEN 2 AND 6 AND correct_option_id IS NOT NULL) "
            "OR (question_type IN ('NUMERICAL', 'WRITTEN') AND jsonb_array_length(options_snapshot) = 0 "
            "AND correct_option_id IS NULL)",
            name="ck_solo_questions_type_shape",
        ),
        Index("ix_solo_questions_attempt", "attempt_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("solo_attempts.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    question_type: Mapped[str] = mapped_column(String(24), nullable=False)
    max_marks: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    prompt_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    options_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    correct_option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grading_rubric_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    worked_explanation_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    original_extract: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SoloAnswerModel(Base):
    __tablename__ = "solo_answers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "question_id"], ["solo_questions.attempt_id", "solo_questions.id"],
            name="fk_solo_answers_attempt_question", ondelete="CASCADE",
        ),
        UniqueConstraint("attempt_id", "question_id", name="uq_solo_answers_attempt_question"),
        CheckConstraint(
            "(selected_option_id IS NOT NULL AND answer_text IS NULL) "
            "OR (selected_option_id IS NULL AND answer_text IS NOT NULL)",
            name="ck_solo_answers_one_input",
        ),
        CheckConstraint(
            "grading_status IN ('SELF_CHECK_PENDING', 'PENDING', 'IN_PROGRESS', 'RETRYABLE', 'UNAVAILABLE', 'GRADED')",
            name="ck_solo_answers_grading_status",
        ),
        CheckConstraint(
            "mark_provenance IN ('DETERMINISTIC_OPTION', 'DETERMINISTIC_NUMERICAL', 'SELF_ASSESSED', 'AI_RUBRIC')",
            name="ck_solo_answers_provenance",
        ),
        CheckConstraint(
            "(grading_status = 'GRADED' AND earned_marks IS NOT NULL AND graded_at IS NOT NULL) "
            "OR (grading_status <> 'GRADED' AND earned_marks IS NULL AND graded_at IS NULL)",
            name="ck_solo_answers_final_grade",
        ),
        CheckConstraint(
            "(grading_status = 'SELF_CHECK_PENDING' AND mark_provenance = 'SELF_ASSESSED') "
            "OR grading_status <> 'SELF_CHECK_PENDING'",
            name="ck_solo_answers_self_check_pending",
        ),
        CheckConstraint(
            "(mark_provenance = 'SELF_ASSESSED' AND grading_status IN ('SELF_CHECK_PENDING', 'GRADED')) "
            "OR (mark_provenance = 'AI_RUBRIC' AND grading_status IN "
            "('PENDING', 'IN_PROGRESS', 'RETRYABLE', 'UNAVAILABLE', 'GRADED')) "
            "OR (mark_provenance IN ('DETERMINISTIC_OPTION', 'DETERMINISTIC_NUMERICAL') "
            "AND grading_status = 'GRADED')",
            name="ck_solo_answers_method_status",
        ),
        CheckConstraint("earned_marks IS NULL OR earned_marks BETWEEN 0 AND 6", name="ck_solo_answers_earned_marks"),
        CheckConstraint("attempt_cycle >= 1 AND attempt_count >= 0", name="ck_solo_answers_attempts"),
        Index(
            "ix_solo_answers_pending_ai", "grading_status", "next_attempt_at",
            postgresql_where=text("mark_provenance = 'AI_RUBRIC' AND grading_status IN ('PENDING', 'RETRYABLE')"),
        ),
        Index("ix_solo_answers_attempt", "attempt_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    question_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    selected_option_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    answer_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    grading_status: Mapped[str] = mapped_column(String(24), nullable=False)
    mark_provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    earned_marks: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_cycle: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    claim_token: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    awarded_criterion_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    feedback: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class SoloSelfCheckModel(Base):
    __tablename__ = "solo_self_checks"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(selected_criterion_ids) = 'array'", name="ck_solo_self_checks_ids_array"),
        CheckConstraint("earned_marks BETWEEN 0 AND 4", name="ck_solo_self_checks_earned_marks"),
    )

    answer_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("solo_answers.id", ondelete="CASCADE"), primary_key=True
    )
    selected_criterion_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    earned_marks: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RoomRewardEnrollmentModel(Base):
    """Start-time eligibility snapshot; missing row means no retroactive reward."""

    __tablename__ = "room_reward_enrollments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "participant_id"],
            ["session_participants.session_id", "session_participants.id"],
            name="fk_room_reward_enrollments_participant", ondelete="CASCADE",
        ),
        UniqueConstraint("session_id", "user_id", name="uq_room_reward_enrollments_session_user"),
        CheckConstraint(
            "home_zone_version >= 1 AND reward_rule_version >= 1",
            name="ck_room_reward_enrollments_versions",
        ),
    )

    session_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    participant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    home_timezone_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    home_zone_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reward_rule_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CompletionReceiptModel(Base):
    """Answer-free handoff; intentionally no FKs to source or user tables."""

    __tablename__ = "learning_completion_receipts"
    __table_args__ = (
        UniqueConstraint("user_id", "source_kind", "source_id", name="uq_learning_receipts_source"),
        CheckConstraint("source_kind IN ('room', 'solo')", name="ck_learning_receipts_source_kind"),
        CheckConstraint("terminal_state = 'FINISHED'", name="ck_learning_receipts_terminal_state"),
        CheckConstraint("canonical_question_count > 0 AND accepted_answer_count = canonical_question_count", name="ck_learning_receipts_coverage"),
        CheckConstraint("home_zone_version >= 1 AND reward_rule_version >= 1 AND completion_state_version >= 1", name="ck_learning_receipts_versions"),
        CheckConstraint("status IN ('pending', 'leased', 'retry_wait', 'posted', 'blocked')", name="ck_learning_receipts_status"),
        CheckConstraint("attempt_count BETWEEN 0 AND 5", name="ck_learning_receipts_attempts"),
        CheckConstraint("latest_accepted_at <= completed_at", name="ck_learning_receipts_time_order"),
        CheckConstraint(
            "(status = 'leased' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'leased' AND lease_token IS NULL AND lease_expires_at IS NULL)",
            name="ck_learning_receipts_lease",
        ),
        CheckConstraint(
            "(status = 'posted' AND posted_at IS NOT NULL AND posting_order IS NOT NULL) "
            "OR (status <> 'posted' AND posted_at IS NULL AND posting_order IS NULL)",
            name="ck_learning_receipts_posted",
        ),
        UniqueConstraint("user_id", "study_date", "posting_order", name="uq_learning_receipts_posting_order"),
        Index("ix_learning_receipts_due", "status", "next_attempt_at", "created_at"),
        Index("ix_learning_receipts_user_day_order", "user_id", "study_date", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    terminal_state: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_question_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    accepted_answer_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    latest_accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    home_timezone_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    home_zone_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    study_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completion_state_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reward_rule_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    lease_token: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    posting_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CoinWalletModel(Base):
    __tablename__ = "coin_wallets"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_coin_wallets_balance"),
        CheckConstraint("state_version >= 1", name="ck_coin_wallets_version"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class QualifiedStudyDayModel(Base):
    __tablename__ = "qualified_study_days"
    __table_args__ = (
        CheckConstraint("total_coins BETWEEN 0 AND 100", name="ck_qualified_study_days_cap"),
        CheckConstraint("qualifying_count >= 1", name="ck_qualified_study_days_count"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    study_date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_coins: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    bonus_awarded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    qualifying_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    first_qualified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CoinLedgerModel(Base):
    __tablename__ = "coin_ledger"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "source_id", name="uq_coin_ledger_source"),
        CheckConstraint("kind IN ('daily_bonus', 'quiz_reward', 'pet_purchase')", name="ck_coin_ledger_kind"),
        CheckConstraint(
            "(kind IN ('daily_bonus', 'quiz_reward') AND amount > 0 AND study_date IS NOT NULL) "
            "OR (kind = 'pet_purchase' AND amount < 0 AND study_date IS NULL)",
            name="ck_coin_ledger_amount_kind",
        ),
        CheckConstraint("balance_after >= 0", name="ck_coin_ledger_balance_after"),
        Index("ix_coin_ledger_user_created", "user_id", "created_at"),
        Index(
            "uq_coin_ledger_daily_bonus", "user_id", "study_date", unique=True,
            postgresql_where=text("kind = 'daily_bonus'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    study_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PetPurchaseModel(Base):
    __tablename__ = "pet_purchases"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_pet_purchases_user_request"),
        UniqueConstraint("id", "user_id", "item_id", name="uq_pet_purchases_owner_item"),
        CheckConstraint("price_charged > 0", name="ck_pet_purchases_price"),
        CheckConstraint(f"item_id IN ({_CATALOG_IDS})", name="ck_pet_purchases_catalog"),
        CheckConstraint(
            "(item_id IN ('pet.owl', 'pet.tortoise', 'pet.fox') AND price_charged = 120) "
            "OR (item_id = 'cosmetic.study_scarf' AND price_charged = 40) "
            "OR (item_id = 'animation.earned_celebration' AND price_charged = 80)",
            name="ck_pet_purchases_catalog_price",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False)
    price_charged: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PetOwnershipModel(Base):
    __tablename__ = "pet_ownership"
    __table_args__ = (
        CheckConstraint(f"item_id IN ({_CATALOG_IDS})", name="ck_pet_ownership_catalog"),
        CheckConstraint("acquisition_kind IN ('starter', 'purchase')", name="ck_pet_ownership_acquisition"),
        CheckConstraint(
            "(acquisition_kind = 'starter' AND item_id IN ('pet.owl', 'pet.tortoise', 'pet.fox') AND purchase_id IS NULL) "
            "OR (acquisition_kind = 'purchase' AND purchase_id IS NOT NULL)",
            name="ck_pet_ownership_starter",
        ),
        ForeignKeyConstraint(
            ["purchase_id", "user_id", "item_id"],
            ["pet_purchases.id", "pet_purchases.user_id", "pet_purchases.item_id"],
            name="fk_pet_ownership_matching_purchase", ondelete="RESTRICT",
        ),
        Index(
            "uq_pet_ownership_one_starter", "user_id", unique=True,
            postgresql_where=text("acquisition_kind = 'starter'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    acquisition_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    purchase_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PetEquipmentModel(Base):
    __tablename__ = "pet_equipment"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "equipped_pet_id"], ["pet_ownership.user_id", "pet_ownership.item_id"],
            name="fk_pet_equipment_pet_owned", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "equipped_cosmetic_id"], ["pet_ownership.user_id", "pet_ownership.item_id"],
            name="fk_pet_equipment_cosmetic_owned", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "equipped_animation_id"], ["pet_ownership.user_id", "pet_ownership.item_id"],
            name="fk_pet_equipment_animation_owned", ondelete="RESTRICT",
        ),
        CheckConstraint(
            "equipped_pet_id IN ('pet.owl', 'pet.tortoise', 'pet.fox')",
            name="ck_pet_equipment_pet",
        ),
        CheckConstraint(
            "equipped_cosmetic_id IS NULL OR equipped_cosmetic_id = 'cosmetic.study_scarf'",
            name="ck_pet_equipment_cosmetic",
        ),
        CheckConstraint(
            "equipped_animation_id IS NULL OR equipped_animation_id = 'animation.earned_celebration'",
            name="ck_pet_equipment_animation",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    equipped_pet_id: Mapped[str] = mapped_column(String(64), nullable=False)
    equipped_cosmetic_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    equipped_animation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


FEATURE_MODEL_TABLES = (
    LearningSettingsModel.__table__,
    SoloAttemptModel.__table__,
    SoloPreparationModel.__table__,
    SoloQuestionModel.__table__,
    SoloAnswerModel.__table__,
    SoloSelfCheckModel.__table__,
    RoomRewardEnrollmentModel.__table__,
    CompletionReceiptModel.__table__,
    CoinWalletModel.__table__,
    QualifiedStudyDayModel.__table__,
    CoinLedgerModel.__table__,
    PetPurchaseModel.__table__,
    PetOwnershipModel.__table__,
    PetEquipmentModel.__table__,
)
