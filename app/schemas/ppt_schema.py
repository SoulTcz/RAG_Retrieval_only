# app/schemas/ppt_schema.py

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class PPTUploadOut(BaseModel):
    """Response after 'Upload PPT' -> chunk -> embed -> store finishes."""
    ppt_id: str
    filename: str
    page_count: int
    num_text_chunks: int
    num_image_chunks: int
    has_images: bool
    message: str = "PDF processed and stored successfully"


class PPTDocumentOut(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    filename: str
    stored_path: str
    uploaded_by: str
    page_count: int
    num_text_chunks: int
    num_image_chunks: int
    has_images: bool
    created_at: datetime

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


class AskRequest(BaseModel):
    """'User Ask Questions' step."""
    question: str
    # Optional: scope the search to one previously-uploaded PDF.
    # If omitted, search runs across every PDF the user has stored.
    ppt_id: Optional[str] = None

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Question cannot be empty")
        return v


class AskResponse(BaseModel):
    """
    'Answer' box in the flowchart. `source` tells you which path produced it:
      - "stored_embeddings"             -> Atlas $vectorSearch matched a chunk above
                                            SIMILARITY_THRESHOLD
      - "stored_embeddings_brute_force" -> same as above, but Atlas search returned
                                            nothing (missing/not-ready index, or a
                                            non-Atlas MongoDB) so an in-memory cosine
                                            similarity scan was used instead
      - "fallback_rechunk"              -> low confidence, so the PDF was re-read/
                                            re-chunked and re-checked (the bottom
                                            fallback loop)
      - "no_data"                       -> nothing usable found to search against;
                                            see `detail` for why
    """
    answer: Optional[str]
    score: float
    source: str
    detail: Optional[str] = None           # human-readable explanation, mainly set on "no_data"
    ppt_id: Optional[str] = None
    chunk_type: Optional[str] = None       # "text" or "image"
    image_file_id: Optional[str] = None    # GridFS file _id, set when the answer came from an image chunk
    image_url: Optional[str] = None        # GET this to fetch/display the image
    page_number: Optional[int] = None
