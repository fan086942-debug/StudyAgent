from app.schemas.chat import Source


def chunk_source(chunk, doc, citation_id, *, score=1.0, text=None):
    """One source/position contract shared by retrieval, study and exam mapping."""
    return Source(
        citation_id=citation_id,
        chunk_id=chunk.id,
        course_id=doc.course_id,
        document_id=doc.id,
        document_name=doc.name,
        document_type=doc.document_type,
        file_type=doc.file_type,
        score=round(score, 5),
        text=chunk.text if text is None else text,
        page=chunk.page,
        chapter=chunk.chapter,
        section=chunk.section,
        block_index=chunk.block_index,
        location_type=chunk.location_type,
        file_url=f"/api/documents/{doc.id}/file"
        + (f"#page={chunk.page}" if doc.file_type == "pdf" and chunk.page else ""),
    )
