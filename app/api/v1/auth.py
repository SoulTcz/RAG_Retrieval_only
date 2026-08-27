# app/api/v1/auth.py

from fastapi import APIRouter, Request, HTTPException, Depends
from datetime import datetime

from app.schemas.user_schema import UserRegister, UserRegisterAdmin, UserLogin, UserOut, Token
from app.core.security import hash_password, verify_password, create_access_token, get_current_user
from app.core.config import ADMIN_CREATION_SECRET

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(user_data: UserRegister, request: Request):
    users_collection = request.app.mongodb["users"]

    # Duplicate email/username check
    existing_user = await users_collection.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    existing_username = await users_collection.find_one({"username": user_data.username})
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")

    # Plain password ko kabhi store nahi karte — hash karke rakhte hain
    new_user = {
        "email": user_data.email,
        "username": user_data.username,
        "full_name": user_data.full_name,
        "hashed_password": hash_password(user_data.password),
        "is_active": True,
        "is_admin": False,          # by-default normal user, admin manually True hoga DB me
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    result = await users_collection.insert_one(new_user)
    created_user = await users_collection.find_one({"_id": result.inserted_id})
    created_user["_id"] = str(created_user["_id"])  # ObjectId ko string me convert
    return created_user


@router.post("/register-admin", response_model=UserOut, status_code=201)
async def register_admin(user_data: UserRegisterAdmin, request: Request):
    """
    Normal /register jaisa hi hai, bas ek extra 'secret_key' field chahiye
    jo .env ke ADMIN_CREATION_SECRET se match karni chahiye.
    Isse random log khud ko admin nahi bana sakte.
    """
    if user_data.secret_key != ADMIN_CREATION_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin creation secret")

    users_collection = request.app.mongodb["users"]

    if await users_collection.find_one({"email": user_data.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    if await users_collection.find_one({"username": user_data.username}):
        raise HTTPException(status_code=400, detail="Username already taken")

    new_admin = {
        "email": user_data.email,
        "username": user_data.username,
        "full_name": user_data.full_name,
        "hashed_password": hash_password(user_data.password),
        "is_active": True,
        "is_admin": True,           # <-- yehi fark hai normal register se
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    result = await users_collection.insert_one(new_admin)
    created_admin = await users_collection.find_one({"_id": result.inserted_id})
    created_admin["_id"] = str(created_admin["_id"])
    return created_admin


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, request: Request):
    users_collection = request.app.mongodb["users"]

    user = await users_collection.find_one({"email": credentials.email})
    if not user or not verify_password(credentials.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account is inactive")

    # "sub" (subject) me hum email daal rahe hain — token verify karte waqt yehi use hoga
    access_token = create_access_token(data={"sub": user["email"]})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    current_user["_id"] = str(current_user["_id"])
    return current_user
