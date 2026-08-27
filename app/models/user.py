# app/models/user.py
# Week 2: Auth ke liye User model update kiya.
# Note: "hashed_password" kabhi bhi API response me nahi jaana chahiye —
# isliye neeche schemas/user_schema.py me alag "UserOut" banaya hai jisme yeh field hi nahi hai.

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class User(BaseModel):
    """Yeh model MongoDB me jaise store hota hai, waisa hai (password hashed)"""
    id: Optional[str] = Field(default=None, alias="_id")
    email: str
    username: str
    hashed_password: str
    full_name: str
    is_active: bool = True
    is_admin: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}
