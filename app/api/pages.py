"""Server-rendered application pages."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["pages"])
PAGE_PATH = Path(__file__).resolve().parents[1] / "templates" / "investigate.html"
LIBRARY_PATH = Path(__file__).resolve().parents[1] / "templates" / "library.html"


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def investigation_page(request: Request) -> HTMLResponse:
    count = getattr(request.app.state, "indexed_document_count", 50_000)
    if type(count) is not int or count < 0:
        count = 50_000
    html = PAGE_PATH.read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__INDEXED_DOCUMENT_COUNT__", f"{count:,}"))


@router.get("/library", response_class=HTMLResponse, include_in_schema=False)
def document_library_page() -> HTMLResponse:
    return HTMLResponse(LIBRARY_PATH.read_text(encoding="utf-8"))
