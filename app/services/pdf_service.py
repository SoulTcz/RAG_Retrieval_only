# app/services/pdf_service.py
#
# Flowchart steps this file implements:
#   - "Upload PPT (Only in pdf format...)"        -> validated in api/v1/ppt.py,
#                                                     this file only ever opens
#                                                     PDFs.
#   - "If the PDF contain the images part then
#      have to take the screen shots"              -> pdf_has_images() / extract_images()
#   - "extract image take the ss of the image
#      then store in DB"                           -> extract_images() returns the raw
#                                                     image bytes; api/v1/ppt.py pushes
#                                                     them straight into MongoDB (GridFS)
#                                                     — nothing is written to local disk.
#
# Uses PyMuPDF — fast, no external binaries needed (unlike poppler/pdf2image),
# and gives us both text extraction and image extraction from the same
# library.
#
# NOTE: `import fitz` is the OLD import name and is deprecated as of recent
# PyMuPDF releases (the pip package is still called "PyMuPDF"/"pymupdf", but
# the module you import is now `pymupdf`). Using `import fitz` will start
# printing deprecation warnings or stop working entirely in future versions,
# so this file imports `pymupdf` directly.

from typing import List, Dict, Any

import pymupdf


def extract_text_by_page(pdf_path: str) -> List[str]:
    """
    PDF ke har page ka plain text ek list me return karta hai
    (index 0 = page 1, index 1 = page 2, ...).
    Isse hum baad me "kis page pe kya likha hai" ka context image-description
    (Gemini) ke liye use kar paate hain.
    """
    pages_text: List[str] = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            pages_text.append(page.get_text("text"))
    return pages_text


def extract_full_text(pdf_path: str) -> str:
    """Poore PDF ka text ek single string me — chunk_text() ko yehi jaata hai."""
    return "\n".join(extract_text_by_page(pdf_path))


def pdf_has_images(pdf_path: str) -> bool:
    """Flowchart ka decision diamond: 'If the PDF contain the images part'."""
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            if page.get_images(full=True):
                return True
    return False


def extract_images(pdf_path: str) -> List[Dict[str, Any]]:
    """
    PDF ke andar jo bhi embedded images hain unke RAW BYTES nikaal ke return
    karta hai (disk pe kuch save NAHI hota — caller, yaani api/v1/ppt.py, in
    bytes ko seedha MongoDB GridFS me daal deta hai).

    Returns:
        List of {"page_number": int, "image_bytes": bytes, "ext": str}
        — ek entry per image. Agar PDF me koi image nahi hai to empty list.
    """
    results: List[Dict[str, Any]] = []

    with pymupdf.open(pdf_path) as doc:
        for page_index, page in enumerate(doc):
            page_number = page_index + 1
            images = page.get_images(full=True)

            for img in images:
                xref = img[0]
                try:
                    base_image = doc.extract_image(xref)
                except Exception:
                    # Corrupt/unsupported image stream — skip it rather than
                    # failing the whole upload
                    continue

                results.append({
                    "page_number": page_number,
                    "image_bytes": base_image["image"],
                    "ext": base_image.get("ext", "png"),
                })

    return results
