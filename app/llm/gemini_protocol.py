"""Pure request/response mapping for the Gemini generateContent REST API."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.llm.schemas import FunctionCall, LLMResponse


API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def request_body(messages: Sequence[Mapping[str, Any]], tools: Any, schema: Any) -> dict[str, Any]:
    contents, system_parts = [], []
    for message in messages:
        role, parts = message.get("role"), message.get("parts")
        if role == "system":
            system_parts.extend(parts or [])
        elif role in ("user", "model") and isinstance(parts, list):
            contents.append({"role": role, "parts": parts})
        else:
            raise ValueError("Gemini messages require system, user, or model roles and parts")
    body: dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": 0.1}}
    if system_parts:
        body["systemInstruction"] = {"parts": system_parts}
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]
        body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
    if schema:
        body["generationConfig"].update({"responseMimeType": "application/json", "responseSchema": schema})
    return body


def parse_response(payload: Mapping[str, Any], metrics: list[dict[str, Any]], usage: dict[str, int]) -> LLMResponse:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], Mapping):
        raise ValueError("Gemini returned no candidate")
    content = candidates[0].get("content")
    if not isinstance(content, dict) or not isinstance(content.get("parts"), list):
        raise ValueError("Gemini returned malformed content")
    calls, text = [], []
    for part in content["parts"]:
        if not isinstance(part, Mapping):
            continue
        function = part.get("functionCall")
        if isinstance(function, Mapping):
            args = function.get("args") or {}
            if not isinstance(args, dict):
                raise ValueError("Gemini returned malformed function arguments")
            calls.append(FunctionCall(str(function.get("name", "")), args, function.get("id")))
        elif isinstance(part.get("text"), str) and not part.get("thought"):
            text.append(part["text"])
    if not calls and not "".join(text).strip():
        raise ValueError("Gemini returned no text or function call")
    return LLMResponse("".join(text) or None, calls, content, metrics, usage)


def usage_counts(raw: Any) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    return {key: value for key, value in raw.items()
            if key.endswith("TokenCount") and isinstance(value, int)}


def request_metric(attempt: int, elapsed: float, status: int | None,
                   usage: dict[str, int]) -> dict[str, Any]:
    return {"attempt": attempt, "latency_seconds": round(elapsed, 6),
            "http_status": status, "usage": usage}
