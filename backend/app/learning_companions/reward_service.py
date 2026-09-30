"""Authenticated settings, daily invitation and read models for rewards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.answer_submission import AnswerSubmissionModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.session_participant import SessionParticipantModel
from app.db.models.session_question import SessionQuestionModel
from app.db.models.user import UserModel
from app.learning_companions.contracts import (
    CompletionSource,
    HOME_ZONE_VERSION,
    ReceiptStatus,
    RewardDisplayStatus,
    study_date_for,
)
from app.learning_companions.models import (
    CoinWalletModel,
    CompletionReceiptModel,
    LearningSettingsModel,
    QualifiedStudyDayModel,
    RoomRewardEnrollmentModel,
    SoloAnswerModel,
    SoloAttemptModel,
    SoloQuestionModel,
)
from app.learning_companions.reward_policy import StreakSnapshot, reconstruct_streak
from app.learning_companions.reward_repository import _database_now


class LearningAccountUnavailable(ValueError):
    pass


class HomeZoneRequired(ValueError):
    pass


class HomeZoneAlreadySet(ValueError):
    pass


class StaleDailyInvitation(ValueError):
    """The displayed offer belongs to a different home-zone study day."""


class RewardSourceNotFound(ValueError):
    """No retained source or receipt proves this user's ownership."""


class RewardSourceInconsistent(ValueError):
    """A terminal qualifying source lacks its required atomic receipt."""


@dataclass(frozen=True, slots=True)
class HomeZoneSelection:
    home_timezone: str
    home_zone_version: int
    selected_at: datetime


@dataclass(frozen=True, slots=True)
class DailyInvitation:
    study_date: date
    should_open: bool
    reason: str


@dataclass(frozen=True, slots=True)
class RewardOverview:
    home_timezone: str | None
    study_date: date | None
    balance: int
    day_coins: int
    qualifying_count: int
    streak: StreakSnapshot
    pending_receipt_count: int
    delayed_receipt_count: int


@dataclass(frozen=True, slots=True)
class RewardSourceStatus:
    source_kind: CompletionSource
    source_id: UUID
    status: RewardDisplayStatus


class RewardService:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def select_home_zone(self, user_id: UUID, home_timezone: str) -> HomeZoneSelection:
        """A user chooses one IANA zone for the initial release, with no change path."""
        try:
            ZoneInfo(home_timezone)
        except (KeyError, ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("Choose an available IANA timezone.") from error
        with self._session_factory.begin() as session:
            _lock_active_user(session, user_id)
            settings = session.scalar(
                select(LearningSettingsModel)
                .where(LearningSettingsModel.user_id == user_id)
                .with_for_update()
            )
            if settings is None:
                now = _database_now(session)
                settings = LearningSettingsModel(
                    user_id=user_id,
                    home_timezone=home_timezone,
                    home_zone_version=HOME_ZONE_VERSION,
                    zone_selected_at=now,
                    updated_at=now,
                )
                session.add(settings)
            elif settings.home_timezone != home_timezone:
                raise HomeZoneAlreadySet("The home timezone is fixed after selection.")
            return HomeZoneSelection(
                settings.home_timezone,
                settings.home_zone_version,
                settings.zone_selected_at,
            )

    def claim_daily_invitation(self, user_id: UUID) -> DailyInvitation:
        """Read the offer without consuming it before Home actually presents it."""
        with self._session_factory.begin() as session:
            _lock_active_user(session, user_id)
            settings = _locked_settings(session, user_id)
            today = study_date_for(_database_now(session), settings.home_timezone)
            if settings.last_dismissed_study_date == today:
                return DailyInvitation(today, False, "dismissed")
            qualified = session.scalar(
                select(QualifiedStudyDayModel.user_id).where(
                    QualifiedStudyDayModel.user_id == user_id,
                    QualifiedStudyDayModel.study_date == today,
                )
            )
            if qualified is not None:
                return DailyInvitation(today, False, "already_qualified")
            if settings.last_invited_study_date == today:
                return DailyInvitation(today, False, "already_invited")
            return DailyInvitation(today, True, "first_entry")

    def acknowledge_daily_invitation(
        self, user_id: UUID, offered_date: date
    ) -> DailyInvitation:
        """Record a presented modal after Home onShow, never on offer lookup."""
        with self._session_factory.begin() as session:
            _lock_active_user(session, user_id)
            settings = _locked_settings(session, user_id)
            now = _database_now(session)
            today = study_date_for(now, settings.home_timezone)
            if offered_date != today:
                raise StaleDailyInvitation("Invitation day changed; refresh the offer.")
            if settings.last_dismissed_study_date == today:
                return DailyInvitation(today, False, "dismissed")
            qualified = session.scalar(
                select(QualifiedStudyDayModel.user_id).where(
                    QualifiedStudyDayModel.user_id == user_id,
                    QualifiedStudyDayModel.study_date == today,
                )
            )
            if qualified is not None:
                return DailyInvitation(today, False, "already_qualified")
            if settings.last_invited_study_date != today:
                settings.last_invited_study_date = today
                settings.updated_at = now
            return DailyInvitation(today, False, "already_invited")

    def dismiss_daily_invitation(
        self, user_id: UUID, offered_date: date
    ) -> DailyInvitation:
        with self._session_factory.begin() as session:
            _lock_active_user(session, user_id)
            settings = _locked_settings(session, user_id)
            now = _database_now(session)
            today = study_date_for(now, settings.home_timezone)
            if offered_date != today:
                raise StaleDailyInvitation("Invitation day changed; refresh the offer.")
            settings.last_dismissed_study_date = today
            settings.updated_at = now
            return DailyInvitation(today, False, "dismissed")

    def get_overview(self, user_id: UUID) -> RewardOverview:
        with self._session_factory.begin() as session:
            _lock_active_user(session, user_id)
            settings = session.get(LearningSettingsModel, user_id)
            wallet = session.get(CoinWalletModel, user_id)
            pending = session.scalar(
                select(func.count()).select_from(CompletionReceiptModel).where(
                    CompletionReceiptModel.user_id == user_id,
                    CompletionReceiptModel.status.in_(
                        (
                            ReceiptStatus.PENDING.value,
                            ReceiptStatus.LEASED.value,
                            ReceiptStatus.RETRY_WAIT.value,
                        )
                    ),
                )
            ) or 0
            delayed = session.scalar(
                select(func.count()).select_from(CompletionReceiptModel).where(
                    CompletionReceiptModel.user_id == user_id,
                    CompletionReceiptModel.status == ReceiptStatus.BLOCKED.value,
                )
            ) or 0
            if settings is None:
                return RewardOverview(
                    None, None, wallet.balance if wallet else 0, 0, 0,
                    StreakSnapshot(0, 0, None, False), pending, delayed,
                )
            today = study_date_for(_database_now(session), settings.home_timezone)
            day = session.get(QualifiedStudyDayModel, (user_id, today))
            dates = session.scalars(
                select(QualifiedStudyDayModel.study_date).where(
                    QualifiedStudyDayModel.user_id == user_id,
                    QualifiedStudyDayModel.study_date <= today,
                )
            ).all()
            return RewardOverview(
                settings.home_timezone,
                today,
                wallet.balance if wallet else 0,
                day.total_coins if day else 0,
                day.qualifying_count if day else 0,
                reconstruct_streak(dates, today=today),
                pending,
                delayed,
            )

    def get_source_status(
        self, user_id: UUID, source_kind: CompletionSource, source_id: UUID
    ) -> RewardSourceStatus:
        """Read one owner's source without score, answer or peer information.

        A self-contained receipt is authoritative even after educational
        source purge. If no receipt exists, source rows can prove only marking
        or ineligibility; they never mint or imply a coin grant. Rechecking
        the receipt after source reads closes a FINISHED commit between reads.
        """
        with self._session_factory.begin() as session:
            _lock_active_user(session, user_id)
            receipt = _source_receipt(session, user_id, source_kind, source_id)
            if receipt is not None:
                status = _receipt_display_status(receipt)
                return RewardSourceStatus(source_kind, source_id, status)

            if source_kind == CompletionSource.SOLO:
                source_status = _solo_source_status(session, user_id, source_id)
            elif source_kind == CompletionSource.ROOM:
                source_status = _room_source_status(session, user_id, source_id)
            else:
                raise ValueError("Unknown completion source kind.")

            # A terminal source can commit its receipt after the first read.
            receipt = _source_receipt(session, user_id, source_kind, source_id)
            if receipt is not None:
                status = _receipt_display_status(receipt)
                return RewardSourceStatus(source_kind, source_id, status)
            if source_status is None:
                raise RewardSourceInconsistent("Reward status needs server reconciliation.")
            return RewardSourceStatus(source_kind, source_id, source_status)


def _source_receipt(
    session: Session, user_id: UUID, source_kind: CompletionSource, source_id: UUID
) -> CompletionReceiptModel | None:
    return session.scalar(
        select(CompletionReceiptModel).where(
            CompletionReceiptModel.user_id == user_id,
            CompletionReceiptModel.source_kind == source_kind.value,
            CompletionReceiptModel.source_id == source_id,
        )
    )


def _receipt_display_status(receipt: CompletionReceiptModel) -> RewardDisplayStatus:
    if receipt.status == ReceiptStatus.POSTED.value:
        # A cap-limited zero coin grant still has a posted receipt.
        return "credited"
    if receipt.status == ReceiptStatus.BLOCKED.value:
        return "reward_delayed"
    if receipt.status in {
        ReceiptStatus.PENDING.value,
        ReceiptStatus.LEASED.value,
        ReceiptStatus.RETRY_WAIT.value,
    }:
        return "reward_pending"
    raise RewardSourceInconsistent("Reward status needs server reconciliation.")


def _solo_source_status(
    session: Session, user_id: UUID, source_id: UUID
) -> RewardDisplayStatus | None:
    attempt = session.scalar(
        select(SoloAttemptModel).where(
            SoloAttemptModel.id == source_id,
            SoloAttemptModel.owner_id == user_id,
        )
    )
    if attempt is None:
        raise RewardSourceNotFound("Reward source not found.")
    if attempt.status == "AWAITING_MARKING":
        return "awaiting_marking"
    if attempt.status != "FINISHED":
        return "not_eligible"
    question_ids = set(
        session.scalars(
            select(SoloQuestionModel.id).where(SoloQuestionModel.attempt_id == source_id)
        ).all()
    )
    graded_ids = set(
        session.scalars(
            select(SoloAnswerModel.question_id).where(
                SoloAnswerModel.attempt_id == source_id,
                SoloAnswerModel.grading_status == "GRADED",
                SoloAnswerModel.accepted_at <= attempt.terminal_at,
            )
        ).all()
    )
    return None if question_ids and graded_ids == question_ids else "not_eligible"


def _room_source_status(
    session: Session, user_id: UUID, source_id: UUID
) -> RewardDisplayStatus | None:
    participant = session.scalar(
        select(SessionParticipantModel).where(
            SessionParticipantModel.session_id == source_id,
            SessionParticipantModel.user_id == user_id,
        )
    )
    if participant is None:
        raise RewardSourceNotFound("Reward source not found.")
    quiz = session.get(QuizSessionModel, source_id)
    if quiz is None:
        raise RewardSourceNotFound("Reward source not found.")
    enrollment = session.get(RoomRewardEnrollmentModel, (source_id, participant.id))
    if enrollment is None or enrollment.user_id != user_id:
        return "not_eligible"
    if quiz.status == "QUESTION_GRADING":
        pending_answer = session.scalar(
            select(AnswerSubmissionModel.id).where(
                AnswerSubmissionModel.session_id == source_id,
                AnswerSubmissionModel.participant_id == participant.id,
                AnswerSubmissionModel.grading_status != "GRADED",
            ).limit(1)
        )
        return "awaiting_marking" if pending_answer is not None else "not_eligible"
    if quiz.status != "FINISHED":
        return "not_eligible"
    question_ids = set(
        session.scalars(
            select(SessionQuestionModel.id).where(SessionQuestionModel.session_id == source_id)
        ).all()
    )
    graded_ids = set(
        session.scalars(
            select(AnswerSubmissionModel.session_question_id).where(
                AnswerSubmissionModel.session_id == source_id,
                AnswerSubmissionModel.participant_id == participant.id,
                AnswerSubmissionModel.grading_status == "GRADED",
                AnswerSubmissionModel.submitted_at <= quiz.finished_at,
            )
        ).all()
    )
    return None if question_ids and graded_ids == question_ids else "not_eligible"


def _lock_active_user(session: Session, user_id: UUID) -> UserModel:
    user = session.scalar(select(UserModel).where(UserModel.id == user_id).with_for_update())
    if user is None or user.deleted_at is not None or user.suspended_at is not None:
        raise LearningAccountUnavailable("This account cannot use learning rewards.")
    return user


def _locked_settings(session: Session, user_id: UUID) -> LearningSettingsModel:
    settings = session.scalar(
        select(LearningSettingsModel)
        .where(LearningSettingsModel.user_id == user_id)
        .with_for_update()
    )
    if settings is None:
        raise HomeZoneRequired("Choose a home timezone before daily rewards.")
    return settings
