from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.membership import RoomMembershipModel
from app.db.models.quiz_session import QuizSessionModel
from app.db.models.room import RoomModel
from app.db.models.user import UserModel
from app.domain.errors import (
    DuplicateMembershipError,
    AccountDeletedError,
    AccountSuspendedError,
    RoomApplicationError,
    RoomClosedError,
    RoomFullError,
    RoomNotFoundError,
    SessionAlreadyActiveError,
    UserAlreadyInAnotherRoomError,
    UserNotFoundError,
)
from app.domain.member import RoomMember
from app.domain.quiz import QuizSessionStatus


class PostgresMembershipRepository:
    """PostgreSQL-backed membership repository with active-history semantics."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @property
    def session_factory(self) -> sessionmaker[Session]:
        """Expose the shared database seam to adjacent domain services."""

        return self._session_factory

    def add(self, member: RoomMember) -> None:
        """Insert an active membership and translate expected conflicts."""

        try:
            with self._session_factory() as session:
                with session.begin():
                    room = session.scalar(
                        select(RoomModel)
                        .where(RoomModel.id == member.room_id)
                        .with_for_update()
                    )
                    if room is None:
                        raise RoomNotFoundError
                    if room.closed_at is not None:
                        raise RoomClosedError
                    user = session.get(UserModel, member.user_id)
                    if user is None:
                        raise UserNotFoundError
                    if user.deleted_at is not None:
                        raise AccountDeletedError
                    if user.suspended_at is not None:
                        raise AccountSuspendedError
                    session.add(_to_model(member))
                    session.flush()
        except IntegrityError as error:
            self._raise_membership_integrity_error(member, error)

    def join(self, member: RoomMember, _maximum_members: int) -> None:
        """Join under a locked room row and database-enforced active indexes."""

        try:
            with self._session_factory() as session:
                with session.begin():
                    user = session.scalar(
                        select(UserModel)
                        .where(UserModel.id == member.user_id)
                        .with_for_update()
                    )
                    if user is None:
                        raise UserNotFoundError
                    if user.deleted_at is not None:
                        raise AccountDeletedError
                    if user.suspended_at is not None:
                        raise AccountSuspendedError
                    room = session.scalar(
                        select(RoomModel)
                        .where(RoomModel.id == member.room_id)
                        .with_for_update()
                    )
                    if room is None:
                        raise RoomNotFoundError
                    if room.closed_at is not None:
                        raise RoomClosedError

                    active_session = session.scalar(
                        select(QuizSessionModel.id).where(
                            QuizSessionModel.room_id == member.room_id,
                            QuizSessionModel.status.in_(
                                (
                                    QuizSessionStatus.QUESTION_OPEN.value,
                                    QuizSessionStatus.QUESTION_GRADING.value,
                                    QuizSessionStatus.QUESTION_REVEAL.value,
                                )
                            ),
                        )
                    )
                    if active_session is not None:
                        raise SessionAlreadyActiveError

                    active_in_room = session.scalar(
                        select(RoomMembershipModel.id).where(
                            RoomMembershipModel.room_id == member.room_id,
                            RoomMembershipModel.user_id == member.user_id,
                            RoomMembershipModel.left_at.is_(None),
                        )
                    )
                    if active_in_room is not None:
                        raise DuplicateMembershipError

                    active_room = session.scalar(
                        select(RoomMembershipModel.room_id)
                        .where(
                            RoomMembershipModel.user_id == member.user_id,
                            RoomMembershipModel.left_at.is_(None),
                        )
                        .limit(1)
                    )
                    if active_room is not None:
                        raise UserAlreadyInAnotherRoomError

                    active_count = session.scalar(
                        select(func.count(RoomMembershipModel.id)).where(
                            RoomMembershipModel.room_id == member.room_id,
                            RoomMembershipModel.left_at.is_(None),
                        )
                    )
                    if active_count is None or active_count >= room.maximum_members:
                        raise RoomFullError

                    session.add(_to_model(member))
                    session.flush()
        except IntegrityError as error:
            self._raise_join_integrity_error(member, error)

    def list_by_room(self, room_id: UUID) -> tuple[RoomMember, ...]:
        with self._session_factory() as session:
            rows = session.execute(
                select(RoomMembershipModel, UserModel.display_name)
                .join(UserModel, UserModel.id == RoomMembershipModel.user_id)
                .where(
                    RoomMembershipModel.room_id == room_id,
                    RoomMembershipModel.left_at.is_(None),
                )
                .order_by(RoomMembershipModel.joined_at, RoomMembershipModel.id)
            ).all()
            return tuple(
                _to_domain(model, display_name) for model, display_name in rows
            )

    def get_by_room_and_user(
        self,
        room_id: UUID,
        user_id: UUID,
    ) -> RoomMember | None:
        with self._session_factory() as session:
            row = session.execute(
                select(RoomMembershipModel, UserModel.display_name)
                .join(UserModel, UserModel.id == RoomMembershipModel.user_id)
                .where(
                    RoomMembershipModel.room_id == room_id,
                    RoomMembershipModel.user_id == user_id,
                    RoomMembershipModel.left_at.is_(None),
                )
            ).first()
            return None if row is None else _to_domain(row[0], row[1])

    def get_active_room_for_user(self, user_id: UUID) -> UUID | None:
        with self._session_factory() as session:
            return session.scalar(
                select(RoomMembershipModel.room_id)
                .join(RoomModel, RoomModel.id == RoomMembershipModel.room_id)
                .where(
                    RoomMembershipModel.user_id == user_id,
                    RoomMembershipModel.left_at.is_(None),
                    RoomModel.closed_at.is_(None),
                )
                .limit(1)
            )

    def get_room_for_user(self, user_id: UUID) -> UUID | None:
        """Backward-compatible alias for the active-room lookup."""

        return self.get_active_room_for_user(user_id)

    def count_active_by_room(self, room_id: UUID) -> int:
        with self._session_factory() as session:
            count = session.scalar(
                select(func.count(RoomMembershipModel.id)).where(
                    RoomMembershipModel.room_id == room_id,
                    RoomMembershipModel.left_at.is_(None),
                )
            )
            return int(count or 0)

    def count_by_room(self, room_id: UUID) -> int:
        """Backward-compatible alias for the active membership count."""

        return self.count_active_by_room(room_id)

    def clear(self) -> None:
        """Remove all memberships; intended for isolated test database cleanup."""

        with self._session_factory() as session:
            with session.begin():
                session.execute(delete(RoomMembershipModel))

    def _raise_membership_integrity_error(
        self,
        member: RoomMember,
        error: IntegrityError,
    ) -> None:
        if self.get_by_room_and_user(member.room_id, member.user_id) is not None:
            raise DuplicateMembershipError from error
        active_room = self.get_active_room_for_user(member.user_id)
        if active_room is not None:
            raise UserAlreadyInAnotherRoomError from error
        if not _room_exists(self._session_factory, member.room_id):
            raise RoomNotFoundError from error
        raise RoomApplicationError from error

    def _raise_join_integrity_error(
        self,
        member: RoomMember,
        error: IntegrityError,
    ) -> None:
        if self.get_by_room_and_user(member.room_id, member.user_id) is not None:
            raise DuplicateMembershipError from error
        if self.get_active_room_for_user(member.user_id) is not None:
            raise UserAlreadyInAnotherRoomError from error
        raise RoomApplicationError from error


def _to_model(member: RoomMember) -> RoomMembershipModel:
    return RoomMembershipModel(
        id=uuid4(),
        room_id=member.room_id,
        user_id=member.user_id,
    )


def _to_domain(model: RoomMembershipModel, display_name: str) -> RoomMember:
    return RoomMember(
        user_id=model.user_id,
        display_name=display_name,
        room_id=model.room_id,
    )


def _room_exists(
    session_factory: sessionmaker[Session],
    room_id: UUID,
) -> bool:
    with session_factory() as session:
        return session.get(RoomModel, room_id) is not None
