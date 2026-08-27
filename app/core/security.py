# app/core/security.py
# Yaha 2 kaam hote hain:
# 1. Password ko hash karna aur verify karna (bcrypt) — plain text kabhi store nahi karte
# 2. JWT access token banana aur verify karna

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

# ---------- Password hashing ----------
# CryptContext bcrypt algorithm use karta hai hashing ke liye
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Plain password ko bcrypt hash me convert karta hai, DB me yehi store hoga"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Login ke time user ne jo password diya, usse DB ke hash se match karta hai"""
    return pwd_context.verify(plain_password, hashed_password)


# ---------- JWT tokens ----------
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    JWT token banata hai.
    'data' me hum usually {"sub": user_email} jaisa payload dete hain.
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """Token ko decode karta hai. Invalid/expired hone par exception raise hoti hai."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------- Dependency: current logged-in user nikalne ke liye ----------
# HTTPBearer -> Swagger ke "Authorize" popup me sirf ek simple "Value" box dega
# jaha tumhe bas apna token paste karna hai. koi client_id/client_secret/form nahi.
bearer_scheme = HTTPBearer()


async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    """
    Har protected route isko Depends() ke through use karega.
    Yeh token se email nikal ke DB se poora user object laata hai.
    """
    token = credentials.credentials  # "Bearer <token>" me se sirf <token> part
    payload = decode_access_token(token)
    email: str = payload.get("sub")
    if email is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = await request.app.mongodb["users"].find_one({"email": email})
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_current_admin_user(current_user: dict = Depends(get_current_user)):
    """Admin-only routes ke liye — Week 3 me use hoga"""
    if not current_user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
