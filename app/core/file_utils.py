# app/core/file_utils.py
# Image upload validation aur saving ke liye utility functions

import os
import uuid
from app.core.config import (
    ALLOWED_EXTENSIONS, MAX_FILE_SIZE, UPLOAD_FOLDER,
    PDF_ALLOWED_EXTENSIONS, MAX_PDF_SIZE,
)


def _extension_allowed(filename: str, allowed: set) -> bool:
    """Check karta hai file ka extension allowed list me hai ya nahi"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def allowed_file(filename: str) -> bool:
    """Product-image uploads ke liye (jpg/jpeg/png/webp) — Week 4 feature"""
    return _extension_allowed(filename, ALLOWED_EXTENSIONS)


async def validate_image(file) -> bool:
    """
    Validate the uploaded image file.

    Args:
        file: The uploaded file object.

    Returns:
        bool: True if the file is valid, False otherwise.
    """
    if not file.filename:
        return False

    if not allowed_file(file.filename):
        return False

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        return False
    await file.seek(0)  # Reset pointer so file can be read again later

    return True


def allowed_pdf_file(filename: str) -> bool:
    """Flowchart step: 'Upload PPT (Only in pdf format no other format allowed)'"""
    return _extension_allowed(filename, PDF_ALLOWED_EXTENSIONS)


async def validate_pdf(file) -> bool:
    """
    Validate an uploaded PDF file (extension + size only — real "is this a valid
    PDF" structural check happens later when pdf_service actually opens it with
    PyMuPDF, which will raise a clear error on a corrupt/fake file).
    """
    if not file.filename:
        return False

    if not allowed_pdf_file(file.filename):
        return False

    contents = await file.read()
    if len(contents) > MAX_PDF_SIZE:
        return False
    await file.seek(0)  # Reset pointer so file can be read again later

    return True


def generate_unique_filename(filename: str) -> str:
    """
    Generate a unique filename using UUID, keeping the original extension.

    Args:
        filename: The original filename.

    Returns:
        str: A unique filename, e.g. "3fa85f64-....jpg"
    """
    extension = os.path.splitext(filename)[1]  # already includes the "."
    unique_id = str(uuid.uuid4())
    return f"{unique_id}{extension}"


def save_uploaded_file(file, upload_folder: str = UPLOAD_FOLDER) -> str:
    """
    Save the uploaded file to the specified folder.

    Args:
        file: The uploaded file object.
        upload_folder: The folder where the file should be saved. Defaults to
            UPLOAD_FOLDER from config, but can be overridden for testing.

    Returns:
        str: The path to the saved file.
    """
    # FIX 1: agar folder exist nahi karta, pehle bana lo — warna open() crash karega
    os.makedirs(upload_folder, exist_ok=True)

    file_path = os.path.join(upload_folder, generate_unique_filename(file.filename))

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    return file_path
