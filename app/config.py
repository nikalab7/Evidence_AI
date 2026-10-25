"""Read configuration without mutating the process environment or logging secrets."""

from dataclasses import dataclass, field
from pathlib import Path
import os
from collections.abc import Mapping

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = ""
    database_url: str = field(default="", repr=False)
    admin_token: str = field(default="", repr=False)
    investigation_daily_budget: int = 0
    investigation_per_ip_per_minute: int = 2
    investigation_max_concurrent: int = 2
    investigation_timeout_seconds: int = 90
    gemini_request_timeout_seconds: int = 15
    gemini_max_output_tokens: int = 1024
    database_statement_timeout_ms: int = 12_000
    indexed_document_count: int = 50_000

    def __post_init__(self) -> None:
        bounds = {
            "investigation_daily_budget": (0, 100_000),
            "investigation_per_ip_per_minute": (1, 60),
            "investigation_max_concurrent": (1, 4),
            "investigation_timeout_seconds": (5, 300),
            "gemini_request_timeout_seconds": (1, 60),
            "gemini_max_output_tokens": (128, 2048),
            "database_statement_timeout_ms": (1_000, 60_000),
            "indexed_document_count": (1, 1_000_000),
        }
        for name, (minimum, maximum) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")

    @classmethod
    def load(
        cls,
        env_file: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "Settings":
        # Render's environment wins over local values, including explicit blanks.
        values = dict(dotenv_values(
            env_file if env_file is not None else PROJECT_ROOT / ".env",
            interpolate=False,
        ))
        values.update(os.environ if environ is None else environ)
        parsed: dict[str, str | int] = {}
        defaults = cls()
        integer_fields = {
            "investigation_daily_budget", "investigation_per_ip_per_minute",
            "investigation_max_concurrent", "investigation_timeout_seconds",
            "gemini_request_timeout_seconds", "gemini_max_output_tokens",
            "database_statement_timeout_ms", "indexed_document_count",
        }
        for name in cls.__dataclass_fields__:
            raw_value = values.get(name.upper())
            if name in integer_fields:
                try:
                    parsed[name] = int(raw_value) if raw_value not in (None, "") else getattr(defaults, name)
                except (TypeError, ValueError):
                    raise ValueError(f"{name.upper()} must be an integer") from None
            else:
                parsed[name] = (raw_value or "").strip()
        return cls(**parsed)

    def missing_names(self) -> list[str]:
        required = ("gemini_api_key", "gemini_model", "database_url", "admin_token")
        return [name.upper() for name in required if not getattr(self, name)]
