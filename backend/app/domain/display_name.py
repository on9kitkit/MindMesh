"""The single server-authoritative StudyRoom display-name policy."""

from __future__ import annotations

import re
import unicodedata

from app.domain.errors import InvalidDisplayNameError

DISPLAY_NAME_MIN_LENGTH = 1
DISPLAY_NAME_MAX_LENGTH = 40

# These names are deliberately small and describe StudyRoom service
# identities, not ordinary community vocabulary.
RESERVED_DISPLAY_NAMES = frozenset(
    {
        "studyroom",
        "studyroom support",
        "studyroom admin",
        "administrator",
        "moderator",
        "support",
    }
)

# This is an intentionally bounded impersonation boundary. It is not a
# multilingual profanity filter or a substitute for human safety review.
PROHIBITED_DISPLAY_NAME_TERMS = frozenset({"official", "staff"})
_TOKEN_PATTERN = re.compile(r"[\W_]+", re.UNICODE)
_DANGEROUS_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})


def normalize_display_name(raw: str) -> str:
    """Normalize and validate one user-controlled public display name."""

    if not isinstance(raw, str):
        raise InvalidDisplayNameError

    normalized = unicodedata.normalize("NFKC", raw)
    if any(
        unicodedata.category(character) in _DANGEROUS_CATEGORIES
        for character in normalized
    ):
        raise InvalidDisplayNameError

    normalized = " ".join(normalized.strip().split())
    if not normalized:
        raise InvalidDisplayNameError
    if not DISPLAY_NAME_MIN_LENGTH <= len(normalized) <= DISPLAY_NAME_MAX_LENGTH:
        raise InvalidDisplayNameError

    folded = normalized.casefold()
    if folded in RESERVED_DISPLAY_NAMES:
        raise InvalidDisplayNameError

    tokens = {
        token.casefold()
        for token in _TOKEN_PATTERN.split(normalized)
        if token
    }
    if tokens.intersection(PROHIBITED_DISPLAY_NAME_TERMS):
        raise InvalidDisplayNameError
    return normalized
