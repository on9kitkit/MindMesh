from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class InvalidQuestionDefinitionError(ValueError):
    """Raised when a canonical question violates its domain invariants."""


@dataclass(frozen=True, slots=True)
class QuestionOption:
    """One selectable option in a multiple-choice question."""

    id: str
    label: str


@dataclass(frozen=True, slots=True)
class QuestionDefinition:
    """Validated, bank-owned question content before persistence."""

    bank_key: str
    stable_key: str
    position: int
    prompt: str
    options: tuple[QuestionOption, ...]
    correct_option_id: str
    duration_seconds: int
    is_active: bool = True

    def validate(self) -> None:
        """Validate content before it can be inserted or updated."""

        if not self.bank_key.strip() or len(self.bank_key) > 64:
            raise InvalidQuestionDefinitionError(
                "bank_key must be non-blank and at most 64 characters"
            )
        if not self.stable_key.strip() or len(self.stable_key) > 64:
            raise InvalidQuestionDefinitionError(
                "stable_key must be non-blank and at most 64 characters"
            )
        if self.position < 0:
            raise InvalidQuestionDefinitionError("position must be non-negative")
        if not self.prompt.strip():
            raise InvalidQuestionDefinitionError("prompt must be non-blank")
        if not 2 <= len(self.options) <= 6:
            raise InvalidQuestionDefinitionError(
                "options must contain between 2 and 6 items"
            )
        option_ids = [option.id for option in self.options]
        if any(not option.id.strip() for option in self.options):
            raise InvalidQuestionDefinitionError("option IDs must be non-blank")
        if any(len(option.id) > 64 for option in self.options):
            raise InvalidQuestionDefinitionError(
                "option IDs must be at most 64 characters"
            )
        if any(not option.label.strip() for option in self.options):
            raise InvalidQuestionDefinitionError("option labels must be non-blank")
        if len(option_ids) != len(set(option_ids)):
            raise InvalidQuestionDefinitionError("option IDs must be unique")
        if self.correct_option_id not in option_ids:
            raise InvalidQuestionDefinitionError(
                "correct_option_id must identify one supplied option"
            )
        if not 5 <= self.duration_seconds <= 120:
            raise InvalidQuestionDefinitionError(
                "duration_seconds must be between 5 and 120"
            )


@dataclass(frozen=True, slots=True)
class Question:
    """Immutable persisted question read from the authoritative database."""

    id: UUID
    bank_key: str
    stable_key: str
    position: int
    prompt: str
    options: tuple[QuestionOption, ...]
    correct_option_id: str
    duration_seconds: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
