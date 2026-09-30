"""Validated, explicit retention policy values."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os


MAX_ACCEPTED_JWT_LIFETIME_ENV = "STUDYROOM_MAX_ACCEPTED_JWT_LIFETIME_SECONDS"
DEFAULT_BATCH_LIMIT = 100
RETENTION_MAX_BATCH_LIMIT = 100
OUTBOX_SAFETY_MARGIN = timedelta(hours=24)
SAFETY_REPORT_RETENTION = timedelta(days=90)
CLOSED_ROOM_RETENTION = timedelta(days=30)
SOLO_TERMINAL_RETENTION = timedelta(days=30)


class RetentionConfigurationError(ValueError):
    """Raised when an operator-supplied retention setting is unusable."""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class RetentionCutoffs:
    """One database-clock snapshot and the derived inclusive boundaries."""

    database_now: datetime
    safety_report: datetime
    closed_room: datetime
    solo_terminal: datetime
    completed_outbox: datetime


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """The bounded StudyRoom-owned retention policy for one invocation."""

    maximum_accepted_jwt_lifetime: timedelta
    batch_limit: int = DEFAULT_BATCH_LIMIT
    safety_report_retention: timedelta = SAFETY_REPORT_RETENTION
    closed_room_retention: timedelta = CLOSED_ROOM_RETENTION
    solo_terminal_retention: timedelta = SOLO_TERMINAL_RETENTION
    outbox_safety_margin: timedelta = OUTBOX_SAFETY_MARGIN

    def __post_init__(self) -> None:
        if not isinstance(self.maximum_accepted_jwt_lifetime, timedelta):
            raise RetentionConfigurationError(
                "the maximum accepted JWT lifetime must be a duration"
            )
        if not isinstance(self.batch_limit, int) or isinstance(self.batch_limit, bool):
            raise RetentionConfigurationError(
                "the retention batch limit must be an integer"
            )
        if self.maximum_accepted_jwt_lifetime <= timedelta(0):
            raise RetentionConfigurationError(
                "the maximum accepted JWT lifetime must be positive"
            )
        if self.batch_limit < 1 or self.batch_limit > RETENTION_MAX_BATCH_LIMIT:
            raise RetentionConfigurationError(
                f"the retention batch limit must be between 1 and {RETENTION_MAX_BATCH_LIMIT}"
            )
        for name, duration in (
            ("safety report retention", self.safety_report_retention),
            ("closed room retention", self.closed_room_retention),
            ("solo terminal retention", self.solo_terminal_retention),
            ("outbox safety margin", self.outbox_safety_margin),
        ):
            if not isinstance(duration, timedelta):
                raise RetentionConfigurationError(f"{name} must be a duration")
            if duration <= timedelta(0):
                raise RetentionConfigurationError(f"{name} must be positive")

    @property
    def completed_outbox_retention(self) -> timedelta:
        return self.maximum_accepted_jwt_lifetime + self.outbox_safety_margin

    def cutoffs(self, database_now: datetime) -> RetentionCutoffs:
        now = _as_utc(database_now)
        return RetentionCutoffs(
            database_now=now,
            safety_report=now - self.safety_report_retention,
            closed_room=now - self.closed_room_retention,
            solo_terminal=now - self.solo_terminal_retention,
            completed_outbox=now - self.completed_outbox_retention,
        )

    @classmethod
    def from_environment(
        cls,
        *,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
        environ: Mapping[str, str] | None = None,
    ) -> "RetentionPolicy":
        values = os.environ if environ is None else environ
        raw_lifetime = values.get(MAX_ACCEPTED_JWT_LIFETIME_ENV, "").strip()
        if not raw_lifetime:
            raise RetentionConfigurationError(
                f"{MAX_ACCEPTED_JWT_LIFETIME_ENV} is required"
            )
        try:
            lifetime_seconds = int(raw_lifetime, 10)
            lifetime = timedelta(seconds=lifetime_seconds)
        except (OverflowError, ValueError):
            raise RetentionConfigurationError(
                f"{MAX_ACCEPTED_JWT_LIFETIME_ENV} must be a positive integer"
            ) from None
        if lifetime_seconds <= 0:
            raise RetentionConfigurationError(
                f"{MAX_ACCEPTED_JWT_LIFETIME_ENV} must be a positive integer"
            )
        return cls(
            maximum_accepted_jwt_lifetime=lifetime,
            batch_limit=batch_limit,
        )
