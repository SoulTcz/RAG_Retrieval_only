# app/services/gemini_service.py
#
# Flowchart step this file implements:
#   "using the gemini reterive all the info from that image in context to
#    the pdf (ki pdf me us img ki kya jarurat hai or kya kar rha hai)"
#
# i.e. for every screenshot pdf_service.py extracted, we ask Gemini (a
# vision-capable model) to explain what the image is showing and why it's
# in the document, using the surrounding page text as context. That
# description is what actually gets chunked + embedded + stored — it's what
# lets a text question later match an image.
#
# IMPORTANT: free-tier Gemini API keys have very low per-minute limits
# (as low as 5 requests/minute). A PDF with several images can hit that
# limit mid-upload and Gemini returns a 503 ("Deadline expired") or 429
# ("RESOURCE_EXHAUSTED"). describe_image_in_context() now retries transient
# errors with backoff instead of raising immediately — but even after
# retries are exhausted, the CALLER (app/api/v1/ppt.py) is responsible for
# catching the final exception and falling back to a placeholder, so one
# failed image never aborts the whole upload (which is what was silently
# happening before: the exception killed the request before text chunks
# ever got embedded/stored).

import time

from google import genai
from google.genai import types
from google.genai.errors import ServerError, ClientError

from app.core.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_MAX_RETRIES,
    GEMINI_RETRY_BASE_DELAY,
)

_client = None


def _get_client():
    """Client lazily banate hain — agar GEMINI_API_KEY set hi nahi hai to
    import/startup time pe crash nahi hona chahiye, sirf jab actually image
    describe karni ho tab error aana chahiye."""
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your .env file "
                "(see .env.example) to enable image descriptions."
            )
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


PROMPT_TEMPLATE = """You are helping build a searchable knowledge base from a PDF/PPT slide deck.

Here is the text surrounding this image on its page:
---
{context}
---

Look at the attached image and explain, in 2-5 sentences:
1. What the image actually shows (chart, diagram, screenshot, photo, table, icon, etc.)
2. Why it is likely included on this page - what point it supports or illustrates, given the surrounding text.

Write the explanation as plain, self-contained prose someone could search against later -
don't say "the image shows" repeatedly, just describe the content and its purpose directly."""


def _is_retryable(error: Exception) -> bool:
    """503 (UNAVAILABLE/overloaded) aur 429 (RESOURCE_EXHAUSTED/rate limit)
    dono transient hote hain — thodi der ruk ke retry karna sahi hai.
    401/403/400 jaise errors (bad key, bad request) retry karne se theek
    nahi honge, unhe turant upar bhej do."""
    if isinstance(error, ServerError):
        return True
    if isinstance(error, ClientError):
        message = str(error).upper()
        return "RESOURCE_EXHAUSTED" in message or "429" in message
    return False


def describe_image_in_context(image_bytes: bytes, ext: str, context_text: str) -> str:
    """
    Gemini ko image bytes + surrounding page text bhejta hai, aur ek
    description wapas laata hai jo baad me chunk/embed hoke MongoDB me
    store hoti hai.

    NOTE: ab image ka file PATH nahi, RAW BYTES accept karta hai — kyunki
    images ab disk pe save hi nahi hoti, seedha MongoDB GridFS me jaati hain
    (dekho api/v1/ppt.py). `ext` batata hai mime type kya bhejna hai
    ("png", "jpeg", etc — pdf_service.extract_images() se aata hai).

    Agar GEMINI_API_KEY configure nahi hai, to pipeline break nahi hoti —
    ek clearly-labelled placeholder description return hoti hai, taaki
    upload/chunk/embed/store flow bina Gemini key ke bhi test ho sake.

    Rate-limit (429) ya server-overload (503) errors par, GEMINI_MAX_RETRIES
    baar tak exponential backoff ke saath retry karta hai (5s, 10s, 20s...).
    Sab retries fail hone par exception raise karta hai — caller (api/v1/ppt.py)
    ise pakad ke ek placeholder text use karta hai taaki poora upload fail na ho.
    """
    if not GEMINI_API_KEY:
        return (
            f"[Gemini not configured] Image extracted from page context: "
            f"{context_text[:200].strip()}"
        )

    client = _get_client()
    mime_type = "image/png" if ext.lower() == "png" else "image/jpeg"

    last_error: Exception = RuntimeError("Gemini call never attempted")

    for attempt in range(GEMINI_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    PROMPT_TEMPLATE.format(context=context_text.strip()[:2000]),
                ],
            )
            return response.text.strip()

        except Exception as error:
            last_error = error
            is_last_attempt = attempt == GEMINI_MAX_RETRIES

            if is_last_attempt or not _is_retryable(error):
                raise

            delay = GEMINI_RETRY_BASE_DELAY * (2 ** attempt)
            print(
                f"[gemini_service] Attempt {attempt + 1}/{GEMINI_MAX_RETRIES + 1} "
                f"failed ({error}); retrying in {delay:.0f}s..."
            )
            time.sleep(delay)

    raise last_error
