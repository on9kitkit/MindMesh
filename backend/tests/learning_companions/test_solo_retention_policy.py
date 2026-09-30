"""Offline guard for the owner's terminal-only 30-day education purge."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects import postgresql

from app.retention.policy import RetentionPolicy
from app.retention.repository import build_eligible_terminal_solo_ids
from app.retention.summary import RetentionCounts


def test_solo_cutoff_is_30_days_from_authoritative_terminal_instant() -> None:
    now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    policy = RetentionPolicy(maximum_accepted_jwt_lifetime=timedelta(days=1))
    assert policy.cutoffs(now).solo_terminal == now - timedelta(days=30)


def test_selector_is_bounded_and_excludes_nonterminal_pending_marking() -> None:
    now = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
    policy = RetentionPolicy(
        maximum_accepted_jwt_lifetime=timedelta(days=1), batch_limit=17
    )
    statement = build_eligible_terminal_solo_ids(policy.cutoffs(now), policy)
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "solo_attempts.terminal_at <=" in sql
    for terminal in ("FINISHED", "ABANDONED", "FAILED"):
        assert terminal in sql
    assert "AWAITING_MARKING" not in sql
    assert "LIMIT 17" in sql
    assert "learning_completion_receipts" not in sql


def test_summary_keeps_solo_educational_count_separate_from_rewards() -> None:
    summary = RetentionCounts(solo_attempts=3)
    assert summary.solo_attempts == 3
    assert summary.closed_rooms == 0
    assert summary.deletion_outbox_rows == 0
