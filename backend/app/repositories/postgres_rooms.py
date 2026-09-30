from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.membership import RoomMembershipModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.user import UserModel
from app.domain.errors import (
    DuplicateJoinCodeError,
    DuplicateRoomIdError,
    NotRoomMemberError,
    RoomClosedError,
    RoomCreationError,
    RoomNotFoundError,
    RoomOwnerMustCloseError,
    RoomOwnerRequiredError,
    SessionAlreadyActiveError,
    AccountDeletedError,
    UserNotFoundError,
)
from app.domain.member import RoomMember
from app.domain.quiz import QuizSessionStatus
from app.domain.room import Room
from app.domain.room_lifecycle import RoomCloseOutcome, RoomLeaveOutcome


class PostgresRoomRepository:
    """PostgreSQL-backed room repository."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, room: Room) -> None:
        try:
            with self._session_factory() as session:
                with session.begin():
                    session.add(
                        RoomModel(
                            id=room.id,
                            owner_id=room.owner_id,
                            name=room.name,
                            join_code=room.join_code,
                            maximum_members=room.maximum_members,
                            closed_at=room.closed_at,
                            quiz_mode=room.quiz_mode,
                            education_level=room.education_level,
                            quiz_subject=room.quiz_subject,
                            quiz_topic=room.quiz_topic,
                            target_total_marks=room.target_total_marks,
                        )
                    )
        except IntegrityError as error:
            if self.get_by_id(room.id) is not None:
                raise DuplicateRoomIdError from error
            if self.get_by_join_code(room.join_code) is not None:
                raise DuplicateJoinCodeError from error
            raise RoomCreationError from error

    def create_with_owner(self, room: Room, owner: RoomMember) -> None:
        """Create the room and active owner membership in one transaction."""

        try:
            with self._session_factory() as session:
                with session.begin():
                    user = session.scalar(
                        select(UserModel)
                        .where(UserModel.id == room.owner_id)
                        .with_for_update()
                    )
                    if user is None:
                        raise RoomCreationError
                    if user.deleted_at is not None:
                        raise AccountDeletedError
                    room_model = RoomModel(
                        id=room.id,
                        owner_id=room.owner_id,
                        name=room.name,
                        join_code=room.join_code,
                        maximum_members=room.maximum_members,
                        closed_at=room.closed_at,
                        quiz_mode=room.quiz_mode,
                        education_level=room.education_level,
                        quiz_subject=room.quiz_subject,
                        quiz_topic=room.quiz_topic,
                        target_total_marks=room.target_total_marks,
                    )
                    session.add(room_model)
                    session.flush()
                    session.add(
                        RoomMembershipModel(
                            room_id=owner.room_id,
                            user_id=owner.user_id,
                        )
                    )
                    session.flush()
        except IntegrityError as error:
            if self.get_by_id(room.id) is not None:
                raise DuplicateRoomIdError from error
            if self.get_by_join_code(room.join_code) is not None:
                raise DuplicateJoinCodeError from error
            raise RoomCreationError from error

    def get_by_id(self, room_id: UUID) -> Room | None:
        with self._session_factory() as session:
            model = session.get(RoomModel, room_id)
            return None if model is None else _to_domain(model)

    def get_by_join_code(self, join_code: str) -> Room | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(RoomModel).where(RoomModel.join_code == join_code)
            )
            return None if model is None else _to_domain(model)

    def leave_member(self, room_id: UUID, user_id: UUID) -> RoomLeaveOutcome:
        """End one non-owner membership under the room lifecycle lock."""

        with self._session_factory() as session:
            with session.begin():
                room = _lock_room(session, room_id)
                if room is None:
                    raise RoomNotFoundError
                if room.owner_id == user_id:
                    raise RoomOwnerMustCloseError

                memberships = list(
                    session.scalars(
                        select(RoomMembershipModel)
                        .where(
                            RoomMembershipModel.room_id == room_id,
                            RoomMembershipModel.user_id == user_id,
                        )
                        .order_by(
                            RoomMembershipModel.joined_at.desc(),
                            RoomMembershipModel.id.desc(),
                        )
                    ).all()
                )
                if not memberships:
                    raise NotRoomMemberError

                active_membership = next(
                    (
                        membership
                        for membership in memberships
                        if membership.left_at is None
                    ),
                    None,
                )
                if active_membership is None:
                    latest_left_at = next(
                        (
                            membership.left_at
                            for membership in memberships
                            if membership.left_at is not None
                        ),
                        None,
                    )
                    if latest_left_at is None:
                        raise NotRoomMemberError
                    return RoomLeaveOutcome(
                        room_id=room_id,
                        user_id=user_id,
                        left_at=latest_left_at,
                        already_left=True,
                    )

                if room.closed_at is not None:
                    raise RoomClosedError
                if _active_session_exists(session, room_id):
                    raise SessionAlreadyActiveError

                locked_membership = session.scalar(
                    select(RoomMembershipModel)
                    .where(
                        RoomMembershipModel.id == active_membership.id,
                        RoomMembershipModel.left_at.is_(None),
                    )
                    .with_for_update()
                )
                if locked_membership is None:
                    raise NotRoomMemberError
                left_at = _database_clock(session)
                locked_membership.left_at = left_at
                locked_membership.ready_at = None
                session.flush()
                return RoomLeaveOutcome(
                    room_id=room_id,
                    user_id=user_id,
                    left_at=left_at,
                    already_left=False,
                )

    def close_room(self, room_id: UUID, owner_id: UUID) -> RoomCloseOutcome:
        """Close a room and end all active memberships in one transaction."""

        with self._session_factory() as session:
            with session.begin():
                room = _lock_room(session, room_id)
                if room is None:
                    raise RoomNotFoundError
                if room.owner_id != owner_id:
                    raise RoomOwnerRequiredError
                if room.closed_at is not None:
                    return RoomCloseOutcome(
                        room_id=room_id,
                        closed_at=room.closed_at,
                        already_closed=True,
                    )
                if _active_session_exists(session, room_id):
                    raise SessionAlreadyActiveError

                closed_at = _database_clock(session)
                room.closed_at = closed_at
                session.execute(
                    update(RoomMembershipModel)
                    .where(
                        RoomMembershipModel.room_id == room_id,
                        RoomMembershipModel.left_at.is_(None),
                    )
                    .values(left_at=closed_at, ready_at=None)
                )
                session.flush()
                return RoomCloseOutcome(
                    room_id=room_id,
                    closed_at=closed_at,
                    already_closed=False,
                )

    def clear(self) -> None:
        """Remove all rooms; intended for isolated test database cleanup."""

        with self._session_factory() as session:
            with session.begin():
                session.execute(delete(RoomModel))


def _to_domain(model: RoomModel) -> Room:
    return Room(
        id=model.id,
        owner_id=model.owner_id,
        name=model.name,
        join_code=model.join_code,
        maximum_members=model.maximum_members,
        closed_at=model.closed_at,
        quiz_mode=model.quiz_mode,
        education_level=model.education_level,
        quiz_subject=model.quiz_subject,
        quiz_topic=model.quiz_topic,
        target_total_marks=model.target_total_marks,
    )


def _lock_room(session: Session, room_id: UUID) -> RoomModel | None:
    return session.scalar(
        select(RoomModel).where(RoomModel.id == room_id).with_for_update()
    )


def _active_session_exists(session: Session, room_id: UUID) -> bool:
    session_id = session.scalar(
        select(QuizSessionModel.id).where(
            QuizSessionModel.room_id == room_id,
            QuizSessionModel.status.in_(
                (
                    QuizSessionStatus.QUESTION_OPEN.value,
                    "QUESTION_GRADING",
                    QuizSessionStatus.QUESTION_REVEAL.value,
                )
            ),
        )
    )
    return session_id is not None


def _database_clock(session: Session) -> datetime:
    value = session.scalar(select(func.clock_timestamp()))
    if not isinstance(value, datetime):
        raise RoomCreationError
    return value
