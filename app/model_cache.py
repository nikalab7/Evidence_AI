"""Load FastEmbed from the project's prebuilt model cache."""

from pathlib import Path

from fastembed import TextEmbedding


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_CACHE_DIR = PROJECT_ROOT / ".model_cache"


def load_model(model_name: str, *, threads: int = 1) -> TextEmbedding:
    """Load a cached model without allowing runtime network downloads."""
    if threads < 1:
        raise ValueError("threads must be at least 1")
    return TextEmbedding(
        model_name=model_name,
        cache_dir=str(MODEL_CACHE_DIR),
        threads=threads,
        local_files_only=True,
    )
