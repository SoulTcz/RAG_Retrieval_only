# app/services/text_utils.py
# Flowchart step: "Chunking that pdf"
# (moved here from the project root — this is a generic text utility, so it
# lives with the other business-logic services instead of at top level)

from typing import List


def chunk_text(text: str, chunk_size: int = 450, overlap: int = 0) -> List[str]:

    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap  # thoda overlap rakhte hue aage badho

    return chunks