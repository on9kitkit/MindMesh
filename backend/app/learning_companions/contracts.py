"""Typed, server-owned solo and reward contracts.

Source completion holds only its room/solo lock when inserting an answer-free
receipt. A separate reward claim releases its row lock before the posting
transaction locks user/tombstone, receipt, wallet and study day in that order.
Account deletion locks user first, then source rows, and removes receipts and
reward rows in its local transaction. No receipt has a user or source FK.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Mapping
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.adaptive_quiz import (
    MAX_MARK_BUDGET,
    MAX_WRITTEN_ANSWER_LENGTH,
    MIN_MARK_BUDGET,
    validate_subject_and_topic,
)


REWARD_RULE_VERSION = 1
HOME_ZONE_VERSION = 1
DAILY_COIN_CAP = 100
DAILY_BONUS_COINS = 30
QUALIFYING_QUIZ_COINS = 20
SELF_ASSESSED_WRITTEN_MAX_MARKS = 4
AI_WRITTEN_MIN_MARKS = 5
MAX_WRITTEN_MARKS = 6


class SoloAttemptStatus(StrEnum):
    PREPARING = "PREPARING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_MARKING = "AWAITING_MARKING"
    FINISHED = "FINISHED"
    ABANDONED = "ABANDONED"
    FAILED = "FAILED"


class SoloPreparationStatus(StrEnum):
    GENERATING = "GENERATING"
    READY = "READY"
    FAILED = "FAILED"
    CONSUMED = "CONSUMED"


class SoloGradingStatus(StrEnum):
    SELF_CHECK_PENDING = "SELF_CHECK_PENDING"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RETRYABLE = "RETRYABLE"
    UNAVAILABLE = "UNAVAILABLE"
    GRADED = "GRADED"


class MarkProvenance(StrEnum):
    DETERMINISTIC_OPTION = "DETERMINISTIC_OPTION"
    DETERMINISTIC_NUMERICAL = "DETERMINISTIC_NUMERICAL"
    SELF_ASSESSED = "SELF_ASSESSED"
    AI_RUBRIC = "AI_RUBRIC"


class CompletionSource(StrEnum):
    ROOM = "room"
    SOLO = "solo"


class ReceiptStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RETRY_WAIT = "retry_wait"
    POSTED = "posted"
    BLOCKED = "blocked"


class CoinLedgerKind(StrEnum):
    DAILY_BONUS = "daily_bonus"
    QUIZ_REWARD = "quiz_reward"
    PET_PURCHASE = "pet_purchase"


class CatalogKind(StrEnum):
    PET = "pet"
    COSMETIC = "cosmetic"
    ANIMATION = "animation"


@dataclass(frozen=True, slots=True)
class CatalogItem:
    id: str
    kind: CatalogKind
    coin_price: int


PET_CATALOG: Mapping[str, CatalogItem] = MappingProxyType(
    {
        "pet.owl": CatalogItem("pet.owl", CatalogKind.PET, 120),
        "pet.tortoise": CatalogItem("pet.tortoise", CatalogKind.PET, 120),
        "pet.fox": CatalogItem("pet.fox", CatalogKind.PET, 120),
        "cosmetic.study_scarf": CatalogItem(
            "cosmetic.study_scarf", CatalogKind.COSMETIC, 40
        ),
        "animation.earned_celebration": CatalogItem(
            "animation.earned_celebration", CatalogKind.ANIMATION, 80
        ),
    }
)
STARTER_PET_IDS = frozenset({"pet.owl", "pet.tortoise", "pet.fox"})


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SoloCreateRequest(_StrictRequest):
    request_id: UUID = Field(strict=False)
    subject: str = Field(min_length=1, max_length=32)
    topic: str = Field(min_length=1, max_length=40)
    total_marks: int = Field(ge=MIN_MARK_BUDGET, le=MAX_MARK_BUDGET)

    @model_validator(mode="after")
    def require_catalogue_pair(self) -> SoloCreateRequest:
        subject, topic = validate_subject_and_topic(self.subject, self.topic)
        if (subject, topic) != (self.subject, self.topic):
            raise ValueError("Use canonical GCSE subject and topic identifiers.")
        return self


class SoloAnswerRequest(_StrictRequest):
    question_id: UUID = Field(strict=False)
    selected_option_id: str | None = Field(default=None, max_length=64)
    text: str | None = Field(default=None, max_length=MAX_WRITTEN_ANSWER_LENGTH)

    @model_validator(mode="after")
    def require_exactly_one_response(self) -> SoloAnswerRequest:
        if (self.selected_option_id is None) == (self.text is None):
            raise ValueError("Provide exactly one option or text response.")
        if self.selected_option_id is not None and not self.selected_option_id.strip():
            raise ValueError("Option ID must not be blank.")
        if self.text is not None:
            clean = self.text.strip()
            if not clean:
                raise ValueError("Answer text must not be blank.")
            self.text = clean
        return self


class SoloSelfCheckRequest(_StrictRequest):
    # The empty list is an explicit finalized zero, not missing work.
    selected_criterion_ids: list[str] = Field(max_length=SELF_ASSESSED_WRITTEN_MAX_MARKS)

    @model_validator(mode="after")
    def require_unique_criterion_ids(self) -> SoloSelfCheckRequest:
        ids = self.selected_criterion_ids
        if any(not item or len(item) > 64 for item in ids) or len(ids) != len(set(ids)):
            raise ValueError("Criterion IDs must be nonblank, unique and at most 64 characters.")
        return self


class HomeZoneSelectionRequest(_StrictRequest):
    home_timezone: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def require_iana_zone(self) -> HomeZoneSelectionRequest:
        try:
            ZoneInfo(self.home_timezone)
        except (KeyError, ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("Choose an available IANA timezone.") from error
        return self


@dataclass(frozen=True, slots=True)
class SelfCheckCriterion:
    id: str
    marks: int
    marking_point: str
    explanation: str


@dataclass(frozen=True, slots=True)
class LockedSelfCheck:
    question_id: UUID
    locked_answer: str
    intended_answer: str
    max_marks: int
    criteria: tuple[SelfCheckCriterion, ...]


@dataclass(frozen=True, slots=True)
class SelfCheckResolution:
    selected_criterion_ids: tuple[str, ...]
    earned_marks: int


def resolve_self_check(
    locked: LockedSelfCheck, selected_criterion_ids: tuple[str, ...]
) -> SelfCheckResolution:
    """Score the immutable rubric after the owner answer has been locked.

    The service must fetch the owner-bound answer and snapshot before exposing
    `LockedSelfCheck`, and may persist this result exactly once. A repeat with
    the same selected IDs returns the stored result; a changed repeat conflicts.
    """
    if not 1 <= locked.max_marks <= SELF_ASSESSED_WRITTEN_MAX_MARKS:
        raise ValueError("Self-check only applies to one- to four-mark written questions.")
    weights = {criterion.id: criterion.marks for criterion in locked.criteria}
    if (
        len(weights) != len(locked.criteria)
        or not weights
        or any(not key or not 1 <= value <= locked.max_marks for key, value in weights.items())
        or sum(weights.values()) != locked.max_marks
    ):
        raise ValueError("The saved self-check rubric is invalid.")
    if len(selected_criterion_ids) != len(set(selected_criterion_ids)):
        raise ValueError("Criterion IDs must be unique.")
    if any(criterion_id not in weights for criterion_id in selected_criterion_ids):
        raise ValueError("Criterion ID is not in the saved rubric.")
    return SelfCheckResolution(
        selected_criterion_ids=tuple(sorted(selected_criterion_ids)),
        earned_marks=sum(weights[criterion_id] for criterion_id in selected_criterion_ids),
    )


@dataclass(frozen=True, slots=True)
class CompletionEvidence:
    """Only a trusted source transaction may derive this from immutable rows."""

    user_id: UUID
    source_kind: CompletionSource
    source_id: UUID
    terminal_state: str
    canonical_question_count: int
    distinct_accepted_answer_count: int
    latest_original_accepted_at_utc: datetime
    home_timezone_snapshot: str
    home_zone_version: int
    completed_at_utc: datetime
    completion_state_version: int
    reward_rule_version: int = REWARD_RULE_VERSION

    def __post_init__(self) -> None:
        if self.terminal_state != "FINISHED":
            raise ValueError("Only finished source attempts can earn a receipt.")
        if (
            self.canonical_question_count < 1
            or self.distinct_accepted_answer_count != self.canonical_question_count
        ):
            raise ValueError("Completion requires one accepted answer for every question.")
        if self.home_zone_version < 1 or self.completion_state_version < 1:
            raise ValueError("Completion versions must be positive.")
        if self.reward_rule_version != REWARD_RULE_VERSION:
            raise ValueError("Unsupported reward rule version.")
        if (
            self.latest_original_accepted_at_utc.tzinfo is None
            or self.completed_at_utc.tzinfo is None
        ):
            raise ValueError("Completion instants must be timezone-aware.")
        if self.latest_original_accepted_at_utc > self.completed_at_utc:
            raise ValueError("Accepted answers cannot postdate completion.")
        try:
            ZoneInfo(self.home_timezone_snapshot)
        except (KeyError, ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("Completion home timezone is invalid.") from error

    @property
    def study_date(self) -> date:
        return study_date_for(
            self.latest_original_accepted_at_utc,
            self.home_timezone_snapshot,
        )


def study_date_for(accepted_at: datetime, home_timezone: str) -> date:
    """Attribute study to the original server acceptance instant, with DST."""
    if accepted_at.tzinfo is None:
        raise ValueError("Acceptance instant must be timezone-aware.")
    return accepted_at.astimezone(ZoneInfo(home_timezone)).date()


@dataclass(frozen=True, slots=True)
class RewardAmounts:
    daily_bonus: int
    quiz_coins: int

    @property
    def total(self) -> int:
        return self.daily_bonus + self.quiz_coins


def calculate_reward_amounts(
    *, prior_study_day_coins: int, first_qualification: bool
) -> RewardAmounts:
    """Pure arithmetic; ledger posting must still serialize the user/day."""
    if not 0 <= prior_study_day_coins <= DAILY_COIN_CAP:
        raise ValueError("Prior study-day total is outside the daily cap.")
    if first_qualification and prior_study_day_coins != 0:
        raise ValueError("First qualification cannot follow an earlier grant.")
    remaining = DAILY_COIN_CAP - prior_study_day_coins
    bonus = min(DAILY_BONUS_COINS, remaining) if first_qualification else 0
    quiz = min(QUALIFYING_QUIZ_COINS, remaining - bonus)
    return RewardAmounts(daily_bonus=bonus, quiz_coins=quiz)


RewardDisplayStatus = Literal[
    "not_eligible", "awaiting_marking", "reward_pending", "credited", "reward_delayed"
]
