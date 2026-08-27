# app/services/retrieval_service.py
#
# Flowchart steps this file implements (the whole bottom half of the diagram):
#   "User Ask Questions"
#     -> "Select the PDF for the answer"
#          -> [cosine similarity is high enough]  -> "Answer"
#          -> [cosine similarity is NOT high enough]
#                -> "again read the pdf"
#                -> "chunk and embed according to the question user asked"
#                -> "check the cosine similarity"
#                -> "Answer"
#
# IMPORTANT FIX: previously, if MongoDB Atlas's $vectorSearch returned zero
# results (which happens if the Atlas Vector Search index was never created,
# is still building, or this isn't an Atlas cluster at all — a local mongod
# does NOT support $vectorSearch), this whole endpoint would report
# "no PDFs have been uploaded/processed yet" even when the database was
# completely full of chunks and embeddings. answer_question() now falls back
# to MongoVectorStore.brute_force_search() (plain in-memory cosine similarity)
# whenever the Atlas search comes back empty, and only reports "no_data" if
# the collection is genuinely empty.

from typing import Optional, Dict, Any, List

from bson import ObjectId

from app.core.config import (
    SIMILARITY_THRESHOLD,
    FALLBACK_CHUNK_SIZE,
    FALLBACK_CHUNK_OVERLAP,
)
from app.services.text_utils import chunk_text
from app.services.vector_store import get_ppt_vector_store, embed_text, cosine_similarity
from app.services import pdf_service


def _image_url(image_file_id: Optional[str]) -> Optional[str]:
    """GridFS file_id -> URL the client can GET to fetch/display the image."""
    if not image_file_id:
        return None
    return f"/api/v1/ppt/image/{image_file_id}"


async def _resolve_source_link(db, ppt_id: Optional[str]) -> Optional[str]:
    """ppt_id (Mongo _id string) -> stored_path (source_link filter field)."""
    if not ppt_id:
        return None
    try:
        oid = ObjectId(ppt_id)
    except Exception:
        return None
    doc = await db["ppt_documents"].find_one({"_id": oid}, {"stored_path": 1})
    return doc["stored_path"] if doc else None


async def _fallback_rechunk_and_answer(db, question: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flowchart fallback branch: 'If you not find most similar answer using the
    cosine similarity' -> 'again read the pdf' -> 'chunk and embed according
    to the question user asked' -> 'check the cosine similarity' -> 'Answer'.

    We take the PDF behind the best (but still weak) candidate chunk, re-read
    it fresh, re-chunk it at a finer granularity than the original upload-time
    chunking, embed those chunks, and compare each one directly against the
    question with in-memory cosine similarity (no Atlas index round-trip
    needed for this one-off comparison).
    """
    ppt_id = candidate.get("ppt_id")
    ppt_doc = None
    if ppt_id:
        try:
            ppt_doc = await db["ppt_documents"].find_one({"_id": ObjectId(ppt_id)})
        except Exception:
            ppt_doc = None

    stored_path = ppt_doc["stored_path"] if ppt_doc else candidate.get("source_link")
    if not stored_path:
        # No PDF to go back to — just return whatever the original (weak) match was
        image_file_id = candidate.get("image_file_id")
        return {
            "answer": candidate.get("text", ""),
            "score": candidate.get("score", 0.0),
            "source": "stored_embeddings_low_confidence",
            "ppt_id": ppt_id,
            "chunk_type": candidate.get("chunk_type", "text"),
            "image_file_id": image_file_id,
            "image_url": _image_url(image_file_id),
            "page_number": candidate.get("page_number"),
        }

    full_text = pdf_service.extract_full_text(stored_path)
    fine_chunks = [c for c in chunk_text(full_text, FALLBACK_CHUNK_SIZE, FALLBACK_CHUNK_OVERLAP) if c.strip()]

    if not fine_chunks:
        image_file_id = candidate.get("image_file_id")
        return {
            "answer": candidate.get("text", ""),
            "score": candidate.get("score", 0.0),
            "source": "stored_embeddings_low_confidence",
            "ppt_id": ppt_id,
            "chunk_type": candidate.get("chunk_type", "text"),
            "image_file_id": image_file_id,
            "image_url": _image_url(image_file_id),
            "page_number": candidate.get("page_number"),
        }

    question_vec = embed_text(question)
    best_text, best_score = fine_chunks[0], -1.0
    for chunk in fine_chunks:
        chunk_vec = embed_text(chunk)
        score = cosine_similarity(question_vec, chunk_vec)
        if score > best_score:
            best_text, best_score = chunk, score

    return {
        "answer": best_text,
        "score": best_score,
        "source": "fallback_rechunk",
        "ppt_id": ppt_id,
        "chunk_type": "text",
        "image_file_id": None,
        "image_url": None,
        "page_number": None,
    }


async def answer_question(db, question: str, ppt_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Main entry point used by POST /api/v1/ppt/ask.

    1. Search stored chunk embeddings via MongoDB Atlas Vector Search
       ("Select the PDF for the answer"). If that comes back empty (missing/
       not-ready Atlas index, or a non-Atlas MongoDB), fall back to a plain
       in-memory cosine-similarity scan of the same collection so a working
       Atlas index is never a hard requirement.
    2. If the top match's cosine similarity score clears SIMILARITY_THRESHOLD,
       answer directly from it.
    3. Otherwise, take the fallback branch: re-read the source PDF, re-chunk
       it finer, and re-check cosine similarity against the fresh chunks.
    """
    store = get_ppt_vector_store(db)
    source_link = await _resolve_source_link(db, ppt_id)

    results: List[Dict[str, Any]] = await store.search(question, top_k=3, source_link=source_link)

    used_brute_force = False
    if not results:
        results = await store.brute_force_search(question, top_k=3, source_link=source_link)
        used_brute_force = True

    if not results:
        # Genuinely nothing stored (collection empty, or empty for this ppt_id/source_link)
        chunk_count = await store.count(source_link=source_link)
        detail = (
            "No PDFs have been uploaded/processed yet, so there is nothing to search."
            if chunk_count == 0 else
            "Found chunks for this PDF, but none had usable embeddings — try re-uploading it."
        )
        return {
            "answer": None,
            "score": 0.0,
            "source": "no_data",
            "detail": detail,
            "ppt_id": ppt_id,
            "chunk_type": None,
            "image_file_id": None,
            "image_url": None,
            "page_number": None,
        }

    top = results[0]

    if top.get("score", 0.0) >= SIMILARITY_THRESHOLD:
        image_file_id = top.get("image_file_id")
        return {
            "answer": top["text"],
            "score": top["score"],
            "source": "stored_embeddings" if not used_brute_force else "stored_embeddings_brute_force",
            "ppt_id": top.get("ppt_id"),
            "chunk_type": top.get("chunk_type", "text"),
            "image_file_id": image_file_id,
            "image_url": _image_url(image_file_id),
            "page_number": top.get("page_number"),
        }

    return await _fallback_rechunk_and_answer(db, question, top)
