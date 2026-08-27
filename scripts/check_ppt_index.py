"""
Quick diagnostic script: how many chunks are stored, what a sample document
looks like, and what search indexes currently exist on the collection.

FIX: same DB-name bug as create_vector_index.py had ("sample_mflix"/"chunks"
hardcoded, not matching app/core/config.py). Now uses the same config values
as the rest of the app.

Run from the project root:
    python -m scripts.check_ppt_index
"""

from pymongo import MongoClient

from app.core.config import MONGODB_URI, DATABASE_NAME, PPT_CHUNKS_COLLECTION

client = MongoClient(MONGODB_URI)
db = client[DATABASE_NAME]
collection = db[PPT_CHUNKS_COLLECTION]

count = collection.count_documents({})
print(f"Total chunks in {DATABASE_NAME}.{PPT_CHUNKS_COLLECTION}: {count}")

if count > 0:
    sample = collection.find_one({})
    print("Sample doc keys:", list(sample.keys()))
    print("Embedding length:", len(sample.get("embedding", [])))

print("\n--- Search Indexes ---")
for idx in collection.list_search_indexes():
    print(idx)

client.close()
