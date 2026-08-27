# app/core/config.py
# Yaha hum saari environment settings ek jagah define karte hain
# taaki poore project me bar bar os.environ.get() na likhna pade

from decouple import config

# MongoDB connection string .env file se aayegi
MONGODB_URI: str = config("MONGODB_URI")
DATABASE_NAME: str = config("DATABASE_NAME", default="PPT_Reterival")

# JWT settings (Week 2 me use hoga)
SECRET_KEY: str = config("SECRET_KEY", default="change-this-secret-key")
ALGORITHM: str = config("ALGORITHM", default="HS256")
ACCESS_TOKEN_EXPIRE_MINUTES: int = config("ACCESS_TOKEN_EXPIRE_MINUTES", default=180, cast=int)

# Yeh secret sirf admin bante waqt chahiye - .env me set karo, kisi ko mat batao
ADMIN_CREATION_SECRET: str = config("ADMIN_CREATION_SECRET", default="super-secret-admin-key")

# Week 4: File upload settings (product images - existing e-commerce feature)
UPLOAD_FOLDER: str = config("UPLOAD_FOLDER", default="uploads")
MAX_FILE_SIZE: int = config("MAX_FILE_SIZE", default=5 * 1024 * 1024, cast=int)  # 5MB
ALLOWED_EXTENSIONS: set = {"jpg", "jpeg", "png", "webp"}

# ---------------------------------------------------------------------------
# PPT/PDF Retrieval feature (matches the flowchart)
# NOTE: "uploads" folder lives OUTSIDE the app/ package, at the project root.
# These paths are relative to wherever the server process is started from
# (project root), same convention main.py already used for UPLOAD_FOLDER.
# ---------------------------------------------------------------------------

# Where the raw uploaded PDF files are stored
PDF_UPLOAD_FOLDER: str = config("PDF_UPLOAD_FOLDER", default="uploads/ppt")
# Only PDFs are accepted for the PPT upload flow (flowchart: "Only in pdf format")
PDF_ALLOWED_EXTENSIONS: set = {"pdf"}
MAX_PDF_SIZE: int = config("MAX_PDF_SIZE", default=25 * 1024 * 1024, cast=int)  # 25MB

# NOTE: images extracted from PDFs are stored in MongoDB (GridFS, bucket
# "ppt_images"), not on local disk — so there is no PDF_IMAGE_FOLDER setting
# anymore.

# Text chunking settings ("Chunking that pdf" step)
PDF_CHUNK_SIZE: int = config("PDF_CHUNK_SIZE", default=800, cast=int)
PDF_CHUNK_OVERLAP: int = config("PDF_CHUNK_OVERLAP", default=100, cast=int)

# Smaller/finer chunking used only in the fallback re-chunk path
# ("again read the pdf -> chunk and embed according to the question user asked")
FALLBACK_CHUNK_SIZE: int = config("FALLBACK_CHUNK_SIZE", default=400, cast=int)
FALLBACK_CHUNK_OVERLAP: int = config("FALLBACK_CHUNK_OVERLAP", default=80, cast=int)

# Mongo collection that stores the chunk + embedding documents
PPT_CHUNKS_COLLECTION: str = config("PPT_CHUNKS_COLLECTION", default="ppt_chunks")

# Cosine similarity cutoff used at the "Select the PDF for the answer" decision
# diamond in the flowchart. >= threshold -> answer directly from stored chunks.
# < threshold -> take the fallback branch (re-read + re-chunk + re-embed).
SIMILARITY_THRESHOLD: float = config("SIMILARITY_THRESHOLD", default=0.55, cast=float)

# Gemini (used for "using the gemini retrieve all the info from that image
# in context to the pdf")
GEMINI_API_KEY: str = config("GEMINI_API_KEY", default="")
GEMINI_MODEL: str = config("GEMINI_MODEL", default="gemini-2.0-flash")

# Free-tier Gemini keys have very low per-minute limits (often 5 RPM) — a PDF
# with several images can blow through that in one upload. These settings
# make image-description calls resilient instead of crashing the whole
# upload when a 429/503 happens:
#   - retry a failed call a few times with backoff
#   - wait a bit between each image's Gemini call so you don't burst past RPM
GEMINI_MAX_RETRIES: int = config("GEMINI_MAX_RETRIES", default=3, cast=int)
GEMINI_RETRY_BASE_DELAY: float = config("GEMINI_RETRY_BASE_DELAY", default=5.0, cast=float)
GEMINI_CALL_DELAY_SECONDS: float = config("GEMINI_CALL_DELAY_SECONDS", default=0.0, cast=float)
