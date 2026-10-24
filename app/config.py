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
        return cls(**{
            name: (values.get(name.upper()) or "").strip()
            for name in cls.__dataclass_fields__
        })

    def missing_names(self) -> list[str]:
        return [name.upper() for name in self.__dataclass_fields__ if not getattr(self, name)]
