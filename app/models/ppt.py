# app/models/ppt.py
# Ek uploaded PDF/PPT ka metadata record — collection "ppt_documents".
# Actual chunks + embeddings alag collection me hote hain
# (config.PPT_CHUNKS_COLLECTION, dekho app/services/vector_store.py) taaki
# vector search sirf chhote, focused documents pe chale.

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class PPTDocument(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    filename: str                      # original filename jo user ne upload kiya
    stored_path: str                   # disk pe kaha save hui (uploads/ppt/xxxx.pdf) - "source_link"
    uploaded_by: str                   # current_user["email"]
    page_count: int = 0
    num_text_chunks: int = 0
    num_image_chunks: int = 0
    has_images: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}
