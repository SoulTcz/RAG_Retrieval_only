# app/api/v1/users.py
# FIX: Yeh file outdated thi - purane "email_address" field aur na-existing
# "validate_person" function use kar rahi thi. Ab naye User model (email, username,
# full_name, is_admin...) ke hisaab se sahi kiya hai.
#
# NOTE: User CREATE karna ab yahan nahi hai - woh kaam /api/v1/auth/register
# (app/api/v1/auth.py) karta hai, jaha password properly hash hota hai.
# Yaha sirf Read / Update / Delete rakha hai, jo login/register se related nahi.

from fastapi import APIRouter, Request, HTTPException, Depends
from typing import List

from app.schemas.user_schema import UserOut, UpdateUserDTO
from app.core.security import get_current_user, get_current_admin_user

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


# R <=== Read all users (admin-only, kyunki isme sabka data dikhta hai)
@router.get("/", response_model=List[UserOut])
async def read_users(request: Request, admin: dict = Depends(get_current_admin_user)):
    users = await request.app.mongodb["users"].find().to_list(None)
    for u in users:
        u["_id"] = str(u["_id"])
    return users


# R <=== Read one user by email
@router.get("/{email}", response_model=UserOut)
async def read_user_by_email(email: str, request: Request,
                              admin: dict = Depends(get_current_admin_user)):
    user = await request.app.mongodb["users"].find_one({"email": email})
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user["_id"] = str(user["_id"])
    return user


# U <=== Update own profile (logged-in user apna hi profile update kar sakta hai)
@router.put("/me", response_model=UserOut)
async def update_my_profile(user_update: UpdateUserDTO, request: Request,
                             current_user: dict = Depends(get_current_user)):
    update_data = user_update.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    await request.app.mongodb["users"].update_one(
        {"email": current_user["email"]}, {"$set": update_data}
    )
    updated_user = await request.app.mongodb["users"].find_one({"email": current_user["email"]})
    updated_user["_id"] = str(updated_user["_id"])
    return updated_user


# D <=== Delete user by email (admin-only)
@router.delete("/{email}", response_model=dict)
async def delete_user_by_email(email: str, request: Request,
                                admin: dict = Depends(get_current_admin_user)):
    delete_result = await request.app.mongodb["users"].delete_one({"email": email})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "User deleted successfully"}
