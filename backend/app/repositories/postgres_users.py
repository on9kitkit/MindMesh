from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models.user import UserModel
from app.domain.display_name import normalize_display_name
from app.domain.errors import AccountDeletedError, AccountSuspendedError, UserNotFoundError
from app.domain.user import User
from app.repositories.users import validate_suspension_reason_code


class PostgresUserRepository:
    """PostgreSQL-backed application profile repository."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_by_id(self, user_id: UUID) -> User | None:
        with self._session_factory() as session:
            model = session.get(UserModel, user_id)
            return None if model is None else _to_domain(model)

    def upsert_profile(self, user_id: UUID, display_name: str) -> User:
        display_name = normalize_display_name(display_name)
        with self._session_factory() as session:
            with session.begin():
                model = session.scalar(
                    select(UserModel)
                    .where(UserModel.id == user_id)
                    .with_for_update()
                )
                if model is None:
                    model = UserModel(id=user_id, display_name=display_name)
                    session.add(model)
                else:
                    if model.deleted_at is not None:
                        raise AccountDeletedError
                    if model.suspended_at is not None:
                        raise AccountSuspendedError
                    model.display_name = display_name
                session.flush()
                return _to_domain(model)

    def suspend(self, user_id: UUID, reason_code: str) -> User:
        reason_code = validate_suspension_reason_code(reason_code)
        with self._session_factory() as session:
            with session.begin():
                model = session.scalar(
                    select(UserModel)
                    .where(UserModel.id == user_id)
                    .with_for_update()
                )
                if model is None:
                    raise UserNotFoundError
                if model.deleted_at is not None:
                    raise AccountDeletedError
                if model.suspended_at is None:
                    model.suspended_at = datetime.now(timezone.utc)
                model.suspension_reason_code = reason_code
                session.flush()
                return _to_domain(model)

    def unsuspend(self, user_id: UUID) -> User:
        with self._session_factory() as session:
            with session.begin():
                model = session.scalar(
                    select(UserModel)
                    .where(UserModel.id == user_id)
                    .with_for_update()
                )
                if model is None:
                    raise UserNotFoundError
                if model.deleted_at is not None:
                    raise AccountDeletedError
                model.suspended_at = None
                model.suspension_reason_code = None
                session.flush()
                return _to_domain(model)

    def clear(self) -> None:
        """Remove profiles; intended for isolated test database cleanup."""

        with self._session_factory() as session:
            with session.begin():
                session.execute(delete(UserModel))


def _to_domain(model: UserModel) -> User:
    return User(
        id=model.id,
        display_name=model.display_name,
        created_at=model.created_at,
        updated_at=model.updated_at,
        deleted_at=model.deleted_at,
        suspended_at=model.suspended_at,
        suspension_reason_code=model.suspension_reason_code,
    )
