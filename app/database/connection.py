# app/database/connection.py
# Yaha MongoDB connect/disconnect ka logic hai (tumhare purane main.py se yahi liya hai)

from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import MONGODB_URI, DATABASE_NAME


async def startup_db_client(app):
    """App start hote hi MongoDB se connection banata hai"""
    app.mongodb_client = AsyncIOMotorClient(MONGODB_URI)
    app.mongodb = app.mongodb_client.get_database(DATABASE_NAME)
    print("MongoDB connected.")


async def shutdown_db_client(app):
    """App band hote waqt MongoDB connection close karta hai"""
    app.mongodb_client.close()
    print("Database disconnected.")
