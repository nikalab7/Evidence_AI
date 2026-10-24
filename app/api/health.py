"""Basic liveness endpoint; external dependency checks are a separate probe."""

from fastapi import APIRouter


router = APIRouter()


@router.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
