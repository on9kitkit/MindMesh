"""Privacy-safe aggregate results for retention operations."""

from dataclasses import dataclass
from enum import Enum


class RetentionMode(str, Enum):
    DRY_RUN = "dry-run"
    EXECUTE_PURGE = "execute-purge"


@dataclass(frozen=True, slots=True)
class RetentionCounts:
    """Counts only; no row identifiers or retained content are returned."""

    safety_reports: int = 0
    closed_rooms: int = 0
    deletion_outbox_rows: int = 0
    protected_rooms: int = 0
    solo_attempts: int = 0

    @property
    def reports(self) -> int:
        """Short alias for callers presenting category counts."""

        return self.safety_reports

    @property
    def rooms(self) -> int:
        """Short alias for callers presenting category counts."""

        return self.closed_rooms

    @property
    def outbox(self) -> int:
        """Short alias for callers presenting category counts."""

        return self.deletion_outbox_rows


@dataclass(frozen=True, slots=True)
class RetentionRunSummary:
    """Aggregate eligible/deleted counts for one retention invocation."""

    mode: RetentionMode
    eligible: RetentionCounts
    deleted: RetentionCounts

    @property
    def eligible_safety_reports(self) -> int:
        return self.eligible.safety_reports

    @property
    def eligible_closed_rooms(self) -> int:
        return self.eligible.closed_rooms

    @property
    def eligible_deletion_outbox_rows(self) -> int:
        return self.eligible.deletion_outbox_rows

    @property
    def eligible_solo_attempts(self) -> int:
        return self.eligible.solo_attempts

    @property
    def deleted_safety_reports(self) -> int:
        return self.deleted.safety_reports

    @property
    def deleted_closed_rooms(self) -> int:
        return self.deleted.closed_rooms

    @property
    def deleted_deletion_outbox_rows(self) -> int:
        return self.deleted.deletion_outbox_rows

    @property
    def deleted_solo_attempts(self) -> int:
        return self.deleted.solo_attempts
