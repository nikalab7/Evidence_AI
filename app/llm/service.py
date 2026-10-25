"""Local investigation lifecycle: one verified database session and one LLM client."""

from time import perf_counter
from typing import Any

from app.config import Settings
from app.db.connection import EXPECTED_SUPABASE_PROJECT_REF, connect_database, project_ref_from_database_url
from app.llm.agent import investigate
from app.llm.gemini_client import GeminiClient
from app.llm.agent import RetrievalMode
from app.model_cache import load_model


def run_investigation(question: str, *, settings: Settings | None = None, model: Any | None = None,
                      llm_client: Any | None = None,
                      retrieval_mode: RetrievalMode = "semantic") -> dict[str, Any]:
    """Open one fail-closed Supabase connection and reuse it for every tool call."""
    settings = settings or Settings.load()
    if project_ref_from_database_url(settings.database_url) != EXPECTED_SUPABASE_PROJECT_REF:
        raise RuntimeError("database project identity is unknown or is not Evidence_AI")
    total_started = perf_counter()
    connection_started = perf_counter()
    conn = connect_database()
    connection_seconds = perf_counter() - connection_started
    model_started = perf_counter()
    try:
        embedding_model = model if model is not None else load_model("BAAI/bge-small-en-v1.5", threads=1)
    except Exception:
        conn.close()
        raise
    model_seconds = 0.0 if model is not None else perf_counter() - model_started
    owns_llm = llm_client is None
    client = llm_client if llm_client is not None else GeminiClient(settings)
    try:
        result = investigate(
            question, conn=conn, embedding_model=embedding_model, llm_client=client,
            retrieval_mode=retrieval_mode,
            database_statement_timeout_ms=settings.database_statement_timeout_ms,
            deadline=total_started + settings.investigation_timeout_seconds,
            started_at=total_started, database_connection_seconds=connection_seconds,
            model_initialization_seconds=model_seconds,
        )
        output = result.as_dict()
        output["trace"]["database_project_ref"] = EXPECTED_SUPABASE_PROJECT_REF
        return output
    finally:
        conn.close()
        if owns_llm and hasattr(client, "close"):
            client.close()
