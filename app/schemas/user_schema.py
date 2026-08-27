# app/schemas/user_schema.py
# Auth ke liye request/response schemas.
# Yaha "hashed_password" kabhi kisi Response schema me nahi hai — security ke liye important.

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegister(BaseModel):
    """Registration ke time client jo bhejega"""
    email: EmailStr
    username: str
    password: str
    full_name: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters long")
        return v

    @field_validator("username")
    @classmethod
    def username_length(cls, v: str) -> str:
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters long")
        return v


class UserRegisterAdmin(UserRegister):
    """Admin banane ke liye ek extra secret_key chahiye - .env ki value se match karni hogi"""
    secret_key: str


class UserLogin(BaseModel):
    """Login ke time client jo bhejega"""
    email: EmailStr
    password: str


class UserOut(BaseModel):
    """Client ko jo response dikhega — hashed_password kabhi nahi jaayega"""
    id: Optional[str] = Field(default=None, alias="_id")
    email: EmailStr
    username: str
    full_name: str
    is_active: bool
    is_admin: bool
    created_at: datetime

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


class Token(BaseModel):
    """Login successful hone par yeh response jayega"""
    access_token: str
    token_type: str = "bearer"


# ---- Purani wali generic UpdateUserDTO bhi rehne di, future user-profile-update ke liye ----
class UpdateUserDTO(BaseModel):
    full_name: Optional[str] = None
    username: Optional[str] = None
