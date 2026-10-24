"""Small typed structures shared by the Gemini client and investigation loop."""

from dataclasses import asdict, dataclass, field
from typing import Any


MAX_INVESTIGATION_STEPS = 4
MAX_LLM_REQUESTS = 5

FINAL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "central_claim_id": {"type": "STRING"},
        "claims": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "claim_id": {"type": "STRING"},
                    "text": {"type": "STRING"},
                    "citations": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "chunk_id": {"type": "STRING"},
                                "quote": {"type": "STRING"},
                            },
                            "required": ["chunk_id", "quote"],
                        },
                    },
                },
                "required": ["claim_id", "text", "citations"],
            },
        },
        "conflict_groups": {
            "type": "ARRAY",
            "items": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
    },
    "required": ["central_claim_id", "claims", "conflict_groups"],
}


@dataclass(frozen=True)
class FunctionCall:
    name: str
    arguments: dict[str, Any]
    call_id: str | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    function_calls: list[FunctionCall]
    model_content: dict[str, Any]
    request_metrics: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class InvestigationResult:
    status: str
    answer: str
    claims: list[dict[str, Any]]
    central_claim_id: str | None
    trace: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
