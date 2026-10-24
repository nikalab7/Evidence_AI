from app.llm.tools import execute_tool


def test_search_tool_keeps_validation_source_server_side(monkeypatch):
    import app.llm.tools as tools

    text = "Caf\u00e9 payment fact."
    hit = {"chunk_id": "chunk-1", "doc_id": "doc-1", "title": "Report",
           "titles": ["Report", "Report alias"], "sources": [{"source_id": "source-1"}],
           "evidence_text": text, "validation_source": {"full_text": text, "start_char": 0,
           "end_char": len(text)}, "score": 0.5}
    monkeypatch.setattr(tools, "search", lambda *_args, **_kwargs: [hit])
    retrieved = {}
    result, timing = execute_tool(object(), object(), "search_evidence", {"query": "payment fact"},
                                  retrieved=retrieved)
    assert result["results"][0]["chunk_id"] == "chunk-1"
    assert "sources" not in result["results"][0]
    assert retrieved["chunk-1"]["sources"][0]["source_id"] == "source-1"
    assert retrieved["chunk-1"]["validation_source"]["full_text"] == text
    assert timing["tool"] == "search_evidence"
    assert timing["total_seconds"] >= 0


def test_get_document_only_reads_documents_previously_found(monkeypatch):
    import app.llm.tools as tools

    def fail_if_called(*_args):
        raise AssertionError("unretrieved document IDs must not reach SQL")

    monkeypatch.setattr(tools, "read_document_context", fail_if_called)
    result, _ = execute_tool(object(), None, "get_document", {"doc_id": "invented"},
                             retrieved={"chunk": {"doc_id": "doc-found"}})
    assert result == {"error": "document_not_in_retrieved_evidence"}


def test_get_document_preserves_source_provenance_after_search(monkeypatch):
    import app.llm.tools as tools

    expected = {"doc_id": "doc-found", "full_text": "Full source.", "metadata": {},
                "sources": [{"source_id": "source-1", "sentences": ["Full source."]}]}
    calls = []
    monkeypatch.setattr(tools, "read_document_context", lambda _conn, doc_id: calls.append(doc_id) or expected)
    result, timing = execute_tool(object(), None, "get_document", {"doc_id": "doc-found"},
                                  retrieved={"chunk": {"doc_id": "doc-found"}})
    assert calls == ["doc-found"]
    assert result == expected
    assert timing["database_sql_seconds"] >= 0
