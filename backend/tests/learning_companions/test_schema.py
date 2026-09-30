"""Compare frozen additive DDL to typed models without a database connection."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.models.user import UserModel  # noqa: F401: registers referenced users table
from app.db.models.session_participant import SessionParticipantModel  # noqa: F401: registers room snapshot source
from app.learning_companions.models import FEATURE_MODEL_TABLES


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "0012_learning_companions_foundations.py"
)


def _migration():
    spec = spec_from_file_location("learning_companions_foundation_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CaptureOps:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: object) -> None:
        self.statements.append(_clean_ddl(str(statement)))


def _clean_ddl(statement: str) -> str:
    return "\n".join(line.rstrip() for line in statement.strip().splitlines())


def test_frozen_migration_matches_all_fourteen_model_tables_and_indexes() -> None:
    migration = _migration()
    assert migration.down_revision == "0011_content_verification_gate"
    assert migration._TABLE_NAMES == tuple(table.name for table in FEATURE_MODEL_TABLES)
    capture = _CaptureOps()
    migration.op = capture
    migration.upgrade()
    actual_ddl = [
        sql for sql in capture.statements
        if sql.startswith("CREATE TABLE ") or sql.startswith("CREATE INDEX ")
        or sql.startswith("CREATE UNIQUE INDEX ")
    ]
    expected_ddl = []
    for table in FEATURE_MODEL_TABLES:
        expected_ddl.append(_clean_ddl(str(CreateTable(table).compile(dialect=dialect()))))
        expected_ddl.extend(
            _clean_ddl(str(CreateIndex(index).compile(dialect=dialect())))
            for index in sorted(table.indexes, key=lambda item: item.name)
        )
    assert actual_ddl == expected_ddl
    for table in FEATURE_MODEL_TABLES:
        assert f"ALTER TABLE public.{table.name} ENABLE ROW LEVEL SECURITY" in capture.statements
        assert f"REVOKE ALL PRIVILEGES ON TABLE public.{table.name} FROM PUBLIC" in capture.statements
        for role_name in ("anon", "authenticated", "service_role"):
            assert any(
                f"'{table.name}'," in sql and f"'{role_name}'" in sql
                for sql in capture.statements if sql.startswith("DO $$")
            )


def test_receipt_is_answer_free_and_has_no_implicit_user_or_source_lock() -> None:
    receipt = next(table for table in FEATURE_MODEL_TABLES if table.name == "learning_completion_receipts")
    assert not receipt.foreign_keys
    assert {"user_id", "source_kind", "source_id", "latest_accepted_at", "study_date", "terminal_state"} <= set(receipt.columns.keys())
    assert not {"answer_text", "selected_option_id", "earned_marks", "peer_id"} & set(receipt.columns.keys())
    assert {"canonical_question_count", "accepted_answer_count", "home_timezone_snapshot", "completed_at", "completion_state_version"} <= set(receipt.columns.keys())


def test_owner_and_replay_guards_are_in_schema() -> None:
    tables = {table.name: table for table in FEATURE_MODEL_TABLES}
    enrollment = tables["room_reward_enrollments"]
    assert {"session_id", "participant_id", "user_id", "home_timezone_snapshot", "home_zone_version"} <= set(enrollment.columns.keys())
    assert {foreign_key.target_fullname.split(".")[0] for foreign_key in enrollment.foreign_keys} == {"session_participants"}
    active = next(index for index in tables["solo_attempts"].indexes if index.name == "uq_solo_attempts_active_owner")
    assert active.unique and "AWAITING_MARKING" in str(active.dialect_options["postgresql"]["where"])
    assert {constraint.name for constraint in tables["solo_answers"].constraints} >= {
        "uq_solo_answers_attempt_question", "fk_solo_answers_attempt_question",
        "ck_solo_answers_method_status",
    }
    assert {constraint.name for constraint in tables["coin_ledger"].constraints} >= {"uq_coin_ledger_source"}
    daily_bonus = next(index for index in tables["coin_ledger"].indexes if index.name == "uq_coin_ledger_daily_bonus")
    assert daily_bonus.unique and "daily_bonus" in str(daily_bonus.dialect_options["postgresql"]["where"])
    assert {constraint.name for constraint in tables["pet_ownership"].constraints} >= {"fk_pet_ownership_matching_purchase"}
    assert "terminal_at" in tables["solo_attempts"].columns


def test_downgrade_reverses_dependency_order() -> None:
    migration = _migration()
    capture = _CaptureOps()
    migration.op = capture
    migration.downgrade()
    assert capture.statements == [
        f"DROP TABLE public.{table.name}" for table in reversed(FEATURE_MODEL_TABLES)
    ]
