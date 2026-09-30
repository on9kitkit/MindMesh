"""Strict JSON schemas for OpenAI Responses API verification structured outputs.

Both schemas enforce strict Structured Outputs:
- Top-level object with additionalProperties: False.
- Every listed property is marked required; unused variant fields carry explicit null/empty sentinels.
- Closed enumerations matching protocol domain types.
- The 'reasoning' field in blind solve captures a brief learner/examiner answer justification,
  never an instruction or container for hidden model chain-of-thought.
"""

from __future__ import annotations

from typing import Any

from app.generator.verification.protocol import (
    BlindSolveStatus,
    ConsistencyRejectionReason,
    ConsistencyVerdict,
)

FORMAT_NAME_BLIND_SOLVE: str = "quiz_blind_solve"
FORMAT_NAME_CONSISTENCY_ASSESSMENT: str = "quiz_consistency_assessment"

BLIND_SOLVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "solutions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position": {"type": "integer"},
                    "question_type": {
                        "type": "string",
                        "enum": ["MULTIPLE_CHOICE", "NUMERICAL", "WRITTEN"],
                    },
                    "solve_status": {
                        "type": "string",
                        "enum": [status.value for status in BlindSolveStatus],
                    },
                    "selected_option_id": {"type": ["string", "null"]},
                    "numerical_value": {"type": ["string", "null"]},
                    "numerical_unit": {"type": ["string", "null"]},
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "reasoning": {"type": "string"},
                },
                "required": [
                    "position",
                    "question_type",
                    "solve_status",
                    "selected_option_id",
                    "numerical_value",
                    "numerical_unit",
                    "key_points",
                    "reasoning",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["solutions"],
    "additionalProperties": False,
}

CONSISTENCY_ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position": {"type": "integer"},
                    "question_type": {
                        "type": "string",
                        "enum": ["MULTIPLE_CHOICE", "NUMERICAL", "WRITTEN"],
                    },
                    "verdict": {
                        "type": "string",
                        "enum": [v.value for v in ConsistencyVerdict],
                    },
                    "reason": {
                        "type": "string",
                        "enum": [r.value for r in ConsistencyRejectionReason],
                    },
                    "explanation": {"type": "string"},
                },
                "required": [
                    "position",
                    "question_type",
                    "verdict",
                    "reason",
                    "explanation",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}
