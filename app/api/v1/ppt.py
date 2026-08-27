# app/api/v1/ppt.py
#
# This router is the flowchart, turned into an API:
#
#   POST /api/v1/ppt/upload
#       Upload PPT (pdf only) -> if it has images, screenshot + Gemini-describe
#       them -> chunk the pdf text -> embed everything -> store in MongoDB
#       (images go into GridFS, not local disk)
#
#   POST /api/v1/ppt/ask
#       User asks a question -> select the best PDF/chunk via cosine similarity
#       -> if confident, answer directly -> otherwise re-read + re-chunk the
#       PDF and check cosine similarity again -> answer
#
#   GET  /api/v1/ppt/                -> list all uploaded PDFs (id, filename, etc.)
#                                        so the user can grab a ppt_id to scope /ask to
#   GET  /api/v1/ppt/{ppt_id}        -> details of a single uploaded PDF
#   GET  /api/v1/ppt/image/{file_id} -> fetch/display an image extracted from a PDF
#                                        (stored in MongoDB GridFS, not on disk)
#
# Auth: every route requires a logged-in user (flowchart: "Norman user ->
# Login (Token based Login)" happens before any of this).

import io
from datetime import datetime
from typing import List

from bson import ObjectId
from bson.errors import InvalidId
from gridfs.errors import NoFile
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File
from fastapi.responses import Response

from app.core.security import get_current_user
from app.core.file_utils import validate_pdf, save_uploaded_file
from app.core.config import PDF_UPLOAD_FOLDER, PDF_CHUNK_SIZE, PDF_CHUNK_OVERLAP
from app.schemas.ppt_schema import PPTUploadOut, PPTDocumentOut, AskRequest, AskResponse
from app.services import pdf_service
from app.services.text_utils import chunk_text
from app.services.vector_store import get_ppt_vector_store
from app.services import retrieval_service

router = APIRouter(prefix="/api/v1/ppt", tags=["PPT Retrieval"])

# All images extracted from PDFs live in this GridFS bucket (i.e. two
# collections under the hood: ppt_images.files and ppt_images.chunks) —
# nothing is written to local disk for images anymore.
IMAGE_BUCKET_NAME = "ppt_images"


def _serialize_ppt_doc(doc: dict) -> dict:
    """Mongo document (_id is ObjectId) -> plain dict PPTDocumentOut can read."""
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("/", response_model=List[PPTDocumentOut])
async def list_ppts(
    request: Request,
    mine_only: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """
    Returns every uploaded PDF (id, filename, page count, chunk counts, etc.)
    so you can pick a `ppt_id` and pass it to POST /api/v1/ppt/ask to scope
    a question to one specific document.

    Pass ?mine_only=true to see only PDFs you personally uploaded.
    """
    ppt_documents = request.app.mongodb["ppt_documents"]

    query = {"uploaded_by": current_user["email"]} if mine_only else {}
    cursor = ppt_documents.find(query).sort("created_at", -1)
    docs = await cursor.to_list(length=None)

    return [PPTDocumentOut(**_serialize_ppt_doc(doc)) for doc in docs]


@router.get("/{ppt_id}", response_model=PPTDocumentOut)
async def get_ppt(
    ppt_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Details of a single uploaded PDF, e.g. to confirm you picked the right ppt_id."""
    try:
        oid = ObjectId(ppt_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid ppt_id")

    ppt_documents = request.app.mongodb["ppt_documents"]
    doc = await ppt_documents.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="PPT not found")

    return PPTDocumentOut(**_serialize_ppt_doc(doc))


@router.get("/image/{file_id}")
async def get_ppt_image(
    file_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Streams back an image that was extracted from a PDF and stored in
    MongoDB GridFS. This is what `image_url` in an /ask response points to —
    open it in a browser or an <img> tag to actually see the image.
    """
    try:
        oid = ObjectId(file_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid image file_id")

    bucket = AsyncIOMotorGridFSBucket(request.app.mongodb, bucket_name=IMAGE_BUCKET_NAME)

    try:
        grid_out = await bucket.open_download_stream(oid)
        data = await grid_out.read()
    except NoFile:
        raise HTTPException(status_code=404, detail="Image not found")

    content_type = (grid_out.metadata or {}).get("content_type", "application/octet-stream")
    return Response(content=data, media_type=content_type)


@router.post("/upload", response_model=PPTUploadOut, status_code=201)
async def upload_ppt(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Flowchart: "Upload PPT (Only in pdf format no other format allowed)"
    through to "Store that Embedding to the MongoDB 'PPT_Reterival'".
    """
    # ---- Upload PPT (only pdf) ----
    is_valid = await validate_pdf(file)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file: {file.filename}. Only .pdf files are allowed.",
        )

    # NOTE: only the raw PDF file itself is saved to local disk
    # (uploads/ppt/) — images extracted FROM the PDF go into MongoDB
    # GridFS below, never to disk.
    stored_path = save_uploaded_file(file, PDF_UPLOAD_FOLDER)

    # Create the ppt_documents record first so we have a ppt_id to tag
    # every chunk/image with.
    ppt_documents = request.app.mongodb["ppt_documents"]
    insert_result = await ppt_documents.insert_one({
        "filename": file.filename,
        "stored_path": stored_path,
        "uploaded_by": current_user["email"],
        "page_count": 0,
        "num_text_chunks": 0,
        "num_image_chunks": 0,
        "has_images": False,
        "created_at": datetime.utcnow(),
    })
    ppt_id = str(insert_result.inserted_id)

    # ---- Chunking that pdf ----
    pages = pdf_service.extract_text_by_page(stored_path)
    full_text = "\n".join(pages)
    text_chunks = [c for c in chunk_text(full_text, PDF_CHUNK_SIZE, PDF_CHUNK_OVERLAP) if c.strip()]

    text_chunk_docs = [
        {
            "text": chunk,
            "chunk_type": "text",
            "source_link": stored_path,
            "ppt_id": ppt_id,
            "image_file_id": None,
            "page_number": None,
        }
        for chunk in text_chunks
    ]

    # ---- Vector Embedding + Store the TEXT chunks right away ----
    # IMPORTANT: this happens BEFORE image/Gemini processing, on purpose.
    # Gemini calls (below) can fail — rate limits, timeouts, outages — and if
    # that exception is allowed to escape this function, FastAPI aborts the
    # whole request. If text-chunk storage happened only at the very end
    # (after images), a single failed Gemini call would mean NO text chunks
    # got embedded/stored either, even though extraction+chunking succeeded.
    # Storing text chunks first means a Gemini failure only costs you the
    # image descriptions, never the text.
    vector_store = get_ppt_vector_store(request.app.mongodb)
    await vector_store.add_chunks(text_chunk_docs)

    # ---- If the PDF contains images: screenshot -> store in GridFS -> Gemini describe ----
    image_records = pdf_service.extract_images(stored_path)
    has_images = len(image_records) > 0
    image_chunk_docs = []
    num_image_descriptions_failed = 0

    if has_images:
        # Lazy import so the app can still start even if the google-genai
        # package/key isn't configured yet.
        from app.services import gemini_service

        bucket = AsyncIOMotorGridFSBucket(request.app.mongodb, bucket_name=IMAGE_BUCKET_NAME)

        for index, record in enumerate(image_records):
            page_number = record["page_number"]
            image_bytes = record["image_bytes"]
            ext = record["ext"]
            content_type = "image/png" if ext.lower() == "png" else f"image/{ext}"

            try:
                # ---- store the screenshot in MongoDB (GridFS) ----
                filename = f"{ppt_id}_page{page_number}_img{index + 1}.{ext}"
                file_id = await bucket.upload_from_stream(
                    filename,
                    io.BytesIO(image_bytes),
                    metadata={
                        "ppt_id": ppt_id,
                        "page_number": page_number,
                        "content_type": content_type,
                    },
                )

                # ---- Gemini: describe this image in context of the pdf ----
                # page_number is 1-indexed; pages list is 0-indexed
                context_text = pages[page_number - 1] if page_number - 1 < len(pages) else ""
                description = gemini_service.describe_image_in_context(image_bytes, ext, context_text)

                image_chunk_docs.append({
                    "text": description,
                    "chunk_type": "image",
                    "source_link": stored_path,
                    "ppt_id": ppt_id,
                    "image_file_id": str(file_id),
                    "page_number": page_number,
                })
            except Exception as exc:
                # Never let ONE bad image (Gemini rate-limited/timed out,
                # corrupt image bytes, etc.) take down the whole upload.
                # The image itself is already safely in GridFS by this point
                # in most failure cases (only the Gemini call failed) — we
                # just skip adding a chunk for it and keep going.
                num_image_descriptions_failed += 1
                print(f"[ppt.upload] image on page {page_number} failed to process: {exc}")
                continue

        if image_chunk_docs:
            await vector_store.add_chunks(image_chunk_docs)

    num_text_chunks = len(text_chunks)
    num_image_chunks = len(image_chunk_docs)

    await ppt_documents.update_one(
        {"_id": insert_result.inserted_id},
        {"$set": {
            "page_count": len(pages),
            "num_text_chunks": num_text_chunks,
            "num_image_chunks": num_image_chunks,
            "has_images": has_images,
        }},
    )

    message = "PDF processed and stored successfully"
    if num_image_descriptions_failed:
        message += (
            f" ({num_image_descriptions_failed} image(s) could not be described by "
            "Gemini and were skipped — check server logs; likely a rate limit or "
            "timeout. Text chunks were stored regardless.)"
        )

    return PPTUploadOut(
        ppt_id=ppt_id,
        filename=file.filename,
        page_count=len(pages),
        num_text_chunks=num_text_chunks,
        num_image_chunks=num_image_chunks,
        has_images=has_images,
        message=message,
    )


@router.post("/ask", response_model=AskResponse)
async def ask_question(
    payload: AskRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Flowchart: "User Ask Questions" -> "Select the PDF for the answer" ->
    (cosine similarity high enough -> "Answer") OR
    (cosine similarity low -> "again read the pdf" -> "chunk and embed
    according to the question user asked" -> "check the cosine similarity"
    -> "Answer").
    """
    result = await retrieval_service.answer_question(
        db=request.app.mongodb,
        question=payload.question,
        ppt_id=payload.ppt_id,
    )

    if result["source"] == "no_data":
        raise HTTPException(
            status_code=404,
            detail=result.get("detail") or "Nothing found to search against.",
        )

    return AskResponse(**result)
