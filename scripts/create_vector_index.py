"""
Ye script sirf EK BAAR chalani hai (setup step) taaki MongoDB Atlas par
PPT chunks collection ke upar ek Vector Search Index ban jaaye.

$vectorSearch aggregation tabhi kaam karega jab ye index Atlas me exist kare
(sirf collection me embeddings daal dene se automatically nahi ban jata).

FIX: pehle DB_NAME/COLLECTION_NAME yaha hardcoded the ("sample_mflix"/"chunks"),
jo app/core/config.py ki DATABASE_NAME ("PPT_Reterival") se match hi nahi
karte the — matlab yeh index galat database pe ban raha tha. Ab dono jagah
se same config.py se aa rahe hain.

Chalane ka tareeka (project root se):
    python -m scripts.create_vector_index

Requirement: pymongo>=4.7 (motor isi ke upar bana hai, to already available hoga)
"""

import time

from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from app.core.config import MONGODB_URI, DATABASE_NAME, PPT_CHUNKS_COLLECTION

DB_NAME = DATABASE_NAME
COLLECTION_NAME = PPT_CHUNKS_COLLECTION
INDEX_NAME = "vector_index"
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2

client = MongoClient(MONGODB_URI)
collection = client[DB_NAME][COLLECTION_NAME]

search_index_model = SearchIndexModel(
    definition={
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": EMBEDDING_DIM,
                "similarity": "cosine",
            },
            # "filter" type field taaki $vectorSearch me source_link ke hisaab se
            # results ko restrict kar sakein (same link dobara na scrape karna pade)
            {
                "type": "filter",
                "path": "source_link",
            },
        ]
    },
    name=INDEX_NAME,
    type="vectorSearch",
)

print(f"Creating vector search index '{INDEX_NAME}' on {DB_NAME}.{COLLECTION_NAME} ...")
result = collection.create_search_index(model=search_index_model)
print("Index creation requested:", result)

# Index build hone me thoda time lagta hai (Atlas background me karta hai)
print("Waiting for index to become queryable (ye 1-2 min tak le sakta hai)...")
while True:
    indexes = list(collection.list_search_indexes(INDEX_NAME))
    if indexes and indexes[0].get("queryable"):
        print("Index is ready to use.")
        break
    time.sleep(5)

client.close()