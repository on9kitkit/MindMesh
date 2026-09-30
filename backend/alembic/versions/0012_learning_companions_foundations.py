"""Add separate solo-study, answer-free completion receipts, and earned cosmetics.

Revision ID: 0012_learning_companions
Revises: 0011_content_verification_gate

DDL is a frozen PostgreSQL snapshot of the feature models. This migration does
not import application models. Account deletion must delete receipts explicitly:
they intentionally have no user or source foreign keys, preserving the source
lock -> receipt insert -> separate user-first reward transaction order.
No automatic terminal-answer retention duration is established here.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0012_learning_companions"
down_revision: str | None = "0011_content_verification_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SUPABASE_DATA_API_ROLES = ("anon", "authenticated", "service_role")


def _revoke_optional_role(table_name: str, role_name: str) -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_name}') THEN
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM %I',
                        '{table_name}',
                        '{role_name}'
                    );
                END IF;
            END $$;
            """
        )
    )


def _isolate_table(table_name: str) -> None:
    op.execute(sa.text(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM PUBLIC"))
    for role_name in _SUPABASE_DATA_API_ROLES:
        _revoke_optional_role(table_name, role_name)


_TABLE_NAMES = ('learning_settings', 'solo_attempts', 'solo_preparations', 'solo_questions', 'solo_answers', 'solo_self_checks', 'room_reward_enrollments', 'learning_completion_receipts', 'coin_wallets', 'qualified_study_days', 'coin_ledger', 'pet_purchases', 'pet_ownership', 'pet_equipment')


def upgrade() -> None:
    # learning_settings
    op.execute(sa.text("""
CREATE TABLE learning_settings (
	user_id UUID NOT NULL,
	home_timezone VARCHAR(64) NOT NULL,
	home_zone_version SMALLINT DEFAULT 1 NOT NULL,
	zone_selected_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	last_invited_study_date DATE,
	last_dismissed_study_date DATE,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (user_id),
	CONSTRAINT ck_learning_settings_zone_version CHECK (home_zone_version >= 1),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)
    """))
    _isolate_table("learning_settings")

    # solo_attempts
    op.execute(sa.text("""
CREATE TABLE solo_attempts (
	id UUID NOT NULL,
	owner_id UUID NOT NULL,
	request_id UUID NOT NULL,
	status VARCHAR(24) DEFAULT 'PREPARING' NOT NULL,
	state_version BIGINT DEFAULT 1 NOT NULL,
	education_level VARCHAR(16) DEFAULT 'GCSE' NOT NULL,
	subject VARCHAR(32) NOT NULL,
	topic VARCHAR(40) NOT NULL,
	total_marks SMALLINT NOT NULL,
	current_question_position SMALLINT DEFAULT 0 NOT NULL,
	home_timezone_snapshot VARCHAR(64) NOT NULL,
	home_zone_version SMALLINT NOT NULL,
	reward_rule_version SMALLINT DEFAULT 1 NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	terminal_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_solo_attempts_owner_request UNIQUE (owner_id, request_id),
	CONSTRAINT ck_solo_attempts_status CHECK (status IN ('PREPARING', 'READY', 'IN_PROGRESS', 'AWAITING_MARKING', 'FINISHED', 'ABANDONED', 'FAILED')),
	CONSTRAINT ck_solo_attempts_subject_topic CHECK (
    (subject = 'physics' AND topic IN ('energy', 'electricity', 'forces'))
    OR (subject = 'mathematics' AND topic IN ('number', 'algebra', 'geometry'))
    OR (subject = 'biology' AND topic IN ('cells', 'organisation', 'ecology'))
    OR (subject = 'chemistry' AND topic IN
        ('atomic_structure', 'bonding', 'chemical_reactions'))
    OR (subject = 'english_language' AND topic IN
        ('reading_comprehension', 'language_analysis', 'writing_techniques'))
    OR (subject = 'english_literature' AND topic IN
        ('literary_devices', 'character_and_theme', 'poetry_analysis'))
),
	CONSTRAINT ck_solo_attempts_total_marks CHECK (total_marks BETWEEN 5 AND 40),
	CONSTRAINT ck_solo_attempts_education_level CHECK (education_level = 'GCSE'),
	CONSTRAINT ck_solo_attempts_question_position CHECK (current_question_position >= 0),
	CONSTRAINT ck_solo_attempts_state_version CHECK (state_version >= 1),
	CONSTRAINT ck_solo_attempts_zone_version CHECK (home_zone_version >= 1),
	CONSTRAINT ck_solo_attempts_terminal_at CHECK ((status IN ('FINISHED', 'ABANDONED', 'FAILED') AND terminal_at IS NOT NULL) OR (status NOT IN ('FINISHED', 'ABANDONED', 'FAILED') AND terminal_at IS NULL)),
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE RESTRICT
)
    """))
    op.execute(sa.text("""
CREATE INDEX ix_solo_attempts_owner_created ON solo_attempts (owner_id, created_at)
    """))
    op.execute(sa.text("""
CREATE UNIQUE INDEX uq_solo_attempts_active_owner ON solo_attempts (owner_id) WHERE status IN ('PREPARING', 'READY', 'IN_PROGRESS', 'AWAITING_MARKING')
    """))
    _isolate_table("solo_attempts")

    # solo_preparations
    op.execute(sa.text("""
CREATE TABLE solo_preparations (
	id UUID NOT NULL,
	attempt_id UUID NOT NULL,
	status VARCHAR(24) DEFAULT 'GENERATING' NOT NULL,
	state_version BIGINT DEFAULT 1 NOT NULL,
	generation_attempt INTEGER DEFAULT 1 NOT NULL,
	claim_token UUID,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	model_id VARCHAR(64) NOT NULL,
	verification_revision VARCHAR(64),
	verified_content_digest VARCHAR(64),
	error_category VARCHAR(64),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	ready_at TIMESTAMP WITH TIME ZONE,
	consumed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT ck_solo_preparations_status CHECK (status IN ('GENERATING', 'READY', 'FAILED', 'CONSUMED')),
	CONSTRAINT ck_solo_preparations_state_version CHECK (state_version >= 1),
	CONSTRAINT ck_solo_preparations_attempt CHECK (generation_attempt >= 1),
	CONSTRAINT ck_solo_preparations_verified_proof CHECK (status NOT IN ('READY', 'CONSUMED') OR (verification_revision IS NOT NULL AND verified_content_digest IS NOT NULL)),
	UNIQUE (attempt_id),
	FOREIGN KEY(attempt_id) REFERENCES solo_attempts (id) ON DELETE CASCADE
)
    """))
    _isolate_table("solo_preparations")

    # solo_questions
    op.execute(sa.text("""
CREATE TABLE solo_questions (
	id UUID NOT NULL,
	attempt_id UUID NOT NULL,
	position SMALLINT NOT NULL,
	question_type VARCHAR(24) NOT NULL,
	max_marks SMALLINT NOT NULL,
	prompt_snapshot TEXT NOT NULL,
	options_snapshot JSONB NOT NULL,
	correct_option_id VARCHAR(64),
	grading_rubric_snapshot JSONB NOT NULL,
	worked_explanation_snapshot TEXT NOT NULL,
	original_extract TEXT,
	content_fingerprint VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_solo_questions_attempt_position UNIQUE (attempt_id, position),
	CONSTRAINT uq_solo_questions_attempt_id UNIQUE (attempt_id, id),
	CONSTRAINT uq_solo_questions_attempt_fingerprint UNIQUE (attempt_id, content_fingerprint),
	CONSTRAINT ck_solo_questions_position CHECK (position >= 0),
	CONSTRAINT ck_solo_questions_max_marks CHECK (max_marks BETWEEN 1 AND 6),
	CONSTRAINT ck_solo_questions_type CHECK (question_type IN ('MULTIPLE_CHOICE', 'NUMERICAL', 'WRITTEN')),
	CONSTRAINT ck_solo_questions_options_array CHECK (jsonb_typeof(options_snapshot) = 'array'),
	CONSTRAINT ck_solo_questions_rubric_object CHECK (jsonb_typeof(grading_rubric_snapshot) = 'object'),
	CONSTRAINT ck_solo_questions_type_shape CHECK ((question_type = 'MULTIPLE_CHOICE' AND max_marks = 1 AND jsonb_array_length(options_snapshot) BETWEEN 2 AND 6 AND correct_option_id IS NOT NULL) OR (question_type IN ('NUMERICAL', 'WRITTEN') AND jsonb_array_length(options_snapshot) = 0 AND correct_option_id IS NULL)),
	FOREIGN KEY(attempt_id) REFERENCES solo_attempts (id) ON DELETE CASCADE
)
    """))
    op.execute(sa.text("""
CREATE INDEX ix_solo_questions_attempt ON solo_questions (attempt_id)
    """))
    _isolate_table("solo_questions")

    # solo_answers
    op.execute(sa.text("""
CREATE TABLE solo_answers (
	id UUID NOT NULL,
	attempt_id UUID NOT NULL,
	question_id UUID NOT NULL,
	selected_option_id VARCHAR(64),
	answer_text VARCHAR(1000),
	accepted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	grading_status VARCHAR(24) NOT NULL,
	mark_provenance VARCHAR(32) NOT NULL,
	earned_marks SMALLINT,
	graded_at TIMESTAMP WITH TIME ZONE,
	attempt_cycle INTEGER DEFAULT 1 NOT NULL,
	attempt_count INTEGER DEFAULT 0 NOT NULL,
	claim_token UUID,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	next_attempt_at TIMESTAMP WITH TIME ZONE,
	last_error_category VARCHAR(64),
	awarded_criterion_ids JSONB DEFAULT '[]'::jsonb NOT NULL,
	feedback JSONB DEFAULT '{}'::jsonb NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_solo_answers_attempt_question FOREIGN KEY(attempt_id, question_id) REFERENCES solo_questions (attempt_id, id) ON DELETE CASCADE,
	CONSTRAINT uq_solo_answers_attempt_question UNIQUE (attempt_id, question_id),
	CONSTRAINT ck_solo_answers_one_input CHECK ((selected_option_id IS NOT NULL AND answer_text IS NULL) OR (selected_option_id IS NULL AND answer_text IS NOT NULL)),
	CONSTRAINT ck_solo_answers_grading_status CHECK (grading_status IN ('SELF_CHECK_PENDING', 'PENDING', 'IN_PROGRESS', 'RETRYABLE', 'UNAVAILABLE', 'GRADED')),
	CONSTRAINT ck_solo_answers_provenance CHECK (mark_provenance IN ('DETERMINISTIC_OPTION', 'DETERMINISTIC_NUMERICAL', 'SELF_ASSESSED', 'AI_RUBRIC')),
	CONSTRAINT ck_solo_answers_final_grade CHECK ((grading_status = 'GRADED' AND earned_marks IS NOT NULL AND graded_at IS NOT NULL) OR (grading_status <> 'GRADED' AND earned_marks IS NULL AND graded_at IS NULL)),
	CONSTRAINT ck_solo_answers_self_check_pending CHECK ((grading_status = 'SELF_CHECK_PENDING' AND mark_provenance = 'SELF_ASSESSED') OR grading_status <> 'SELF_CHECK_PENDING'),
	CONSTRAINT ck_solo_answers_method_status CHECK ((mark_provenance = 'SELF_ASSESSED' AND grading_status IN ('SELF_CHECK_PENDING', 'GRADED')) OR (mark_provenance = 'AI_RUBRIC' AND grading_status IN ('PENDING', 'IN_PROGRESS', 'RETRYABLE', 'UNAVAILABLE', 'GRADED')) OR (mark_provenance IN ('DETERMINISTIC_OPTION', 'DETERMINISTIC_NUMERICAL') AND grading_status = 'GRADED')),
	CONSTRAINT ck_solo_answers_earned_marks CHECK (earned_marks IS NULL OR earned_marks BETWEEN 0 AND 6),
	CONSTRAINT ck_solo_answers_attempts CHECK (attempt_cycle >= 1 AND attempt_count >= 0)
)
    """))
    op.execute(sa.text("""
CREATE INDEX ix_solo_answers_attempt ON solo_answers (attempt_id)
    """))
    op.execute(sa.text("""
CREATE INDEX ix_solo_answers_pending_ai ON solo_answers (grading_status, next_attempt_at) WHERE mark_provenance = 'AI_RUBRIC' AND grading_status IN ('PENDING', 'RETRYABLE')
    """))
    _isolate_table("solo_answers")

    # solo_self_checks
    op.execute(sa.text("""
CREATE TABLE solo_self_checks (
	answer_id UUID NOT NULL,
	selected_criterion_ids JSONB NOT NULL,
	earned_marks SMALLINT NOT NULL,
	finalized_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (answer_id),
	CONSTRAINT ck_solo_self_checks_ids_array CHECK (jsonb_typeof(selected_criterion_ids) = 'array'),
	CONSTRAINT ck_solo_self_checks_earned_marks CHECK (earned_marks BETWEEN 0 AND 4),
	FOREIGN KEY(answer_id) REFERENCES solo_answers (id) ON DELETE CASCADE
)
    """))
    _isolate_table("solo_self_checks")

    # room_reward_enrollments
    op.execute(sa.text("""
CREATE TABLE room_reward_enrollments (
	session_id UUID NOT NULL,
	participant_id UUID NOT NULL,
	user_id UUID NOT NULL,
	home_timezone_snapshot VARCHAR(64) NOT NULL,
	home_zone_version SMALLINT NOT NULL,
	reward_rule_version SMALLINT NOT NULL,
	enrolled_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (session_id, participant_id),
	CONSTRAINT fk_room_reward_enrollments_participant FOREIGN KEY(session_id, participant_id) REFERENCES session_participants (session_id, id) ON DELETE CASCADE,
	CONSTRAINT uq_room_reward_enrollments_session_user UNIQUE (session_id, user_id),
	CONSTRAINT ck_room_reward_enrollments_versions CHECK (home_zone_version >= 1 AND reward_rule_version >= 1)
)
    """))
    _isolate_table("room_reward_enrollments")

    # learning_completion_receipts
    op.execute(sa.text("""
CREATE TABLE learning_completion_receipts (
	id UUID NOT NULL,
	user_id UUID NOT NULL,
	source_kind VARCHAR(8) NOT NULL,
	source_id UUID NOT NULL,
	terminal_state VARCHAR(16) NOT NULL,
	canonical_question_count SMALLINT NOT NULL,
	accepted_answer_count SMALLINT NOT NULL,
	latest_accepted_at TIMESTAMP WITH TIME ZONE NOT NULL,
	home_timezone_snapshot VARCHAR(64) NOT NULL,
	home_zone_version SMALLINT NOT NULL,
	study_date DATE NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	completion_state_version BIGINT NOT NULL,
	reward_rule_version SMALLINT DEFAULT 1 NOT NULL,
	status VARCHAR(16) DEFAULT 'pending' NOT NULL,
	attempt_count SMALLINT DEFAULT 0 NOT NULL,
	lease_token UUID,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	next_attempt_at TIMESTAMP WITH TIME ZONE,
	last_error_category VARCHAR(64),
	posting_order INTEGER,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	posted_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_learning_receipts_source UNIQUE (user_id, source_kind, source_id),
	CONSTRAINT ck_learning_receipts_source_kind CHECK (source_kind IN ('room', 'solo')),
	CONSTRAINT ck_learning_receipts_terminal_state CHECK (terminal_state = 'FINISHED'),
	CONSTRAINT ck_learning_receipts_coverage CHECK (canonical_question_count > 0 AND accepted_answer_count = canonical_question_count),
	CONSTRAINT ck_learning_receipts_versions CHECK (home_zone_version >= 1 AND reward_rule_version >= 1 AND completion_state_version >= 1),
	CONSTRAINT ck_learning_receipts_status CHECK (status IN ('pending', 'leased', 'retry_wait', 'posted', 'blocked')),
	CONSTRAINT ck_learning_receipts_attempts CHECK (attempt_count BETWEEN 0 AND 5),
	CONSTRAINT ck_learning_receipts_time_order CHECK (latest_accepted_at <= completed_at),
	CONSTRAINT ck_learning_receipts_lease CHECK ((status = 'leased' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'leased' AND lease_token IS NULL AND lease_expires_at IS NULL)),
	CONSTRAINT ck_learning_receipts_posted CHECK ((status = 'posted' AND posted_at IS NOT NULL AND posting_order IS NOT NULL) OR (status <> 'posted' AND posted_at IS NULL AND posting_order IS NULL)),
	CONSTRAINT uq_learning_receipts_posting_order UNIQUE (user_id, study_date, posting_order)
)
    """))
    op.execute(sa.text("""
CREATE INDEX ix_learning_receipts_due ON learning_completion_receipts (status, next_attempt_at, created_at)
    """))
    op.execute(sa.text("""
CREATE INDEX ix_learning_receipts_user_day_order ON learning_completion_receipts (user_id, study_date, created_at, id)
    """))
    _isolate_table("learning_completion_receipts")

    # coin_wallets
    op.execute(sa.text("""
CREATE TABLE coin_wallets (
	user_id UUID NOT NULL,
	balance INTEGER DEFAULT 0 NOT NULL,
	state_version BIGINT DEFAULT 1 NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (user_id),
	CONSTRAINT ck_coin_wallets_balance CHECK (balance >= 0),
	CONSTRAINT ck_coin_wallets_version CHECK (state_version >= 1),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)
    """))
    _isolate_table("coin_wallets")

    # qualified_study_days
    op.execute(sa.text("""
CREATE TABLE qualified_study_days (
	user_id UUID NOT NULL,
	study_date DATE NOT NULL,
	total_coins SMALLINT DEFAULT 0 NOT NULL,
	bonus_awarded BOOLEAN DEFAULT false NOT NULL,
	qualifying_count INTEGER DEFAULT 1 NOT NULL,
	first_qualified_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (user_id, study_date),
	CONSTRAINT ck_qualified_study_days_cap CHECK (total_coins BETWEEN 0 AND 100),
	CONSTRAINT ck_qualified_study_days_count CHECK (qualifying_count >= 1),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)
    """))
    _isolate_table("qualified_study_days")

    # coin_ledger
    op.execute(sa.text("""
CREATE TABLE coin_ledger (
	id UUID NOT NULL,
	user_id UUID NOT NULL,
	kind VARCHAR(16) NOT NULL,
	source_id UUID NOT NULL,
	amount INTEGER NOT NULL,
	balance_after INTEGER NOT NULL,
	study_date DATE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_coin_ledger_source UNIQUE (user_id, kind, source_id),
	CONSTRAINT ck_coin_ledger_kind CHECK (kind IN ('daily_bonus', 'quiz_reward', 'pet_purchase')),
	CONSTRAINT ck_coin_ledger_amount_kind CHECK ((kind IN ('daily_bonus', 'quiz_reward') AND amount > 0 AND study_date IS NOT NULL) OR (kind = 'pet_purchase' AND amount < 0 AND study_date IS NULL)),
	CONSTRAINT ck_coin_ledger_balance_after CHECK (balance_after >= 0),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)
    """))
    op.execute(sa.text("""
CREATE INDEX ix_coin_ledger_user_created ON coin_ledger (user_id, created_at)
    """))
    op.execute(sa.text("""
CREATE UNIQUE INDEX uq_coin_ledger_daily_bonus ON coin_ledger (user_id, study_date) WHERE kind = 'daily_bonus'
    """))
    _isolate_table("coin_ledger")

    # pet_purchases
    op.execute(sa.text("""
CREATE TABLE pet_purchases (
	id UUID NOT NULL,
	user_id UUID NOT NULL,
	request_id UUID NOT NULL,
	item_id VARCHAR(64) NOT NULL,
	price_charged INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_pet_purchases_user_request UNIQUE (user_id, request_id),
	CONSTRAINT uq_pet_purchases_owner_item UNIQUE (id, user_id, item_id),
	CONSTRAINT ck_pet_purchases_price CHECK (price_charged > 0),
	CONSTRAINT ck_pet_purchases_catalog CHECK (item_id IN ('pet.owl', 'pet.tortoise', 'pet.fox', 'cosmetic.study_scarf', 'animation.earned_celebration')),
	CONSTRAINT ck_pet_purchases_catalog_price CHECK ((item_id IN ('pet.owl', 'pet.tortoise', 'pet.fox') AND price_charged = 120) OR (item_id = 'cosmetic.study_scarf' AND price_charged = 40) OR (item_id = 'animation.earned_celebration' AND price_charged = 80)),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)
    """))
    _isolate_table("pet_purchases")

    # pet_ownership
    op.execute(sa.text("""
CREATE TABLE pet_ownership (
	user_id UUID NOT NULL,
	item_id VARCHAR(64) NOT NULL,
	acquisition_kind VARCHAR(16) NOT NULL,
	purchase_id UUID,
	acquired_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (user_id, item_id),
	CONSTRAINT ck_pet_ownership_catalog CHECK (item_id IN ('pet.owl', 'pet.tortoise', 'pet.fox', 'cosmetic.study_scarf', 'animation.earned_celebration')),
	CONSTRAINT ck_pet_ownership_acquisition CHECK (acquisition_kind IN ('starter', 'purchase')),
	CONSTRAINT ck_pet_ownership_starter CHECK ((acquisition_kind = 'starter' AND item_id IN ('pet.owl', 'pet.tortoise', 'pet.fox') AND purchase_id IS NULL) OR (acquisition_kind = 'purchase' AND purchase_id IS NOT NULL)),
	CONSTRAINT fk_pet_ownership_matching_purchase FOREIGN KEY(purchase_id, user_id, item_id) REFERENCES pet_purchases (id, user_id, item_id) ON DELETE RESTRICT,
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)
    """))
    op.execute(sa.text("""
CREATE UNIQUE INDEX uq_pet_ownership_one_starter ON pet_ownership (user_id) WHERE acquisition_kind = 'starter'
    """))
    _isolate_table("pet_ownership")

    # pet_equipment
    op.execute(sa.text("""
CREATE TABLE pet_equipment (
	user_id UUID NOT NULL,
	equipped_pet_id VARCHAR(64) NOT NULL,
	equipped_cosmetic_id VARCHAR(64),
	equipped_animation_id VARCHAR(64),
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (user_id),
	CONSTRAINT fk_pet_equipment_pet_owned FOREIGN KEY(user_id, equipped_pet_id) REFERENCES pet_ownership (user_id, item_id) ON DELETE RESTRICT,
	CONSTRAINT fk_pet_equipment_cosmetic_owned FOREIGN KEY(user_id, equipped_cosmetic_id) REFERENCES pet_ownership (user_id, item_id) ON DELETE RESTRICT,
	CONSTRAINT fk_pet_equipment_animation_owned FOREIGN KEY(user_id, equipped_animation_id) REFERENCES pet_ownership (user_id, item_id) ON DELETE RESTRICT,
	CONSTRAINT ck_pet_equipment_pet CHECK (equipped_pet_id IN ('pet.owl', 'pet.tortoise', 'pet.fox')),
	CONSTRAINT ck_pet_equipment_cosmetic CHECK (equipped_cosmetic_id IS NULL OR equipped_cosmetic_id = 'cosmetic.study_scarf'),
	CONSTRAINT ck_pet_equipment_animation CHECK (equipped_animation_id IS NULL OR equipped_animation_id = 'animation.earned_celebration'),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)
    """))
    _isolate_table("pet_equipment")



def downgrade() -> None:
    for table_name in reversed(_TABLE_NAMES):
        op.execute(sa.text(f"DROP TABLE public.{table_name}"))
