# app/services/vector_store.py
#
# FIX: this file used to be app/mongo_vector_store.py and had the DB name
# hardcoded to "sample_mflix" (leftover from a MongoDB tutorial). That did
# NOT match DATABASE_NAME ("PPT_Reterival") in app/core/config.py, so data
# written here was silently going into the wrong database. Now everything
# is driven from app/core/config.py, same as every other file in the app.
#
# Flowchart steps this file implements:
#   - "Vector Embedding (...)"                 -> add_chunks() / add_texts()
#   - "Store that Embedding to the MongoDB"     -> add_chunks() / add_texts()
#   - "check the cosine similarity" / "Select
#      the PDF for the answer"                 -> search() (Atlas $vectorSearch,
#                                                  which IS cosine similarity
#                                                  because scripts/create_vector_index.py
#                                                  defines the index with
#                                                  similarity="cosine")

from typing import List, Optional, Dict, Any

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import PPT_CHUNKS_COLLECTION

# Embedding model ek hi baar load hota hai jab app start hota hai
_embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 model 384-dimension ke vectors banata hai

# Yeh naam Atlas me banaye gaye Vector Search Index ke naam se match hona chahiye
# (index banane ke liye scripts/create_vector_index.py dekho)
VECTOR_INDEX_NAME = "vector_index"


def embed_text(text: str) -> List[float]:
    """Single string ko embedding vector me convert karta hai."""
    return _embedding_model.encode([text])[0].tolist()


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Batch me multiple strings ko embed karta hai — chunking ke baad yehi use hota hai."""
    if not texts:
        return []
    return _embedding_model.encode(texts).tolist()


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """
    Plain in-memory cosine similarity — Atlas Vector Search index ke bina bhi
    kaam karta hai. Fallback branch me use hota hai (flowchart: 'again read
    the pdf -> chunk and embed according to the question -> check the cosine
    similarity'), jaha hum turant-turant banaye gaye embeddings ko compare
    karte hain bina unhe pehle DB me store kiye.
    """
    a = np.array(vec_a, dtype=float)
    b = np.array(vec_b, dtype=float)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class MongoVectorStore:
    """
    MongoDB Atlas Vector Search se PPT/PDF chunks store aur search karta hai.
    Har chunk ek document ki tarah collection me store hota hai:
        {
            text: str,
            embedding: [float, ...],
            source_link: str,          # uploaded PDF ka stored file path (PDF ki "identity")
            ppt_id: str,               # PPT/PDF document ka Mongo _id (string)
            chunk_type: "text" | "image",
            image_file_id: str | None, # sirf chunk_type == "image" ke liye — GridFS file _id (string)
            page_number: int | None,
        }
    Search ke liye Atlas ka $vectorSearch aggregation stage use hota hai
    (iske liye collection par ek Atlas Search vector index bana hona zaroori hai,
    dekho scripts/create_vector_index.py). Agar wo index missing/not-ready hai
    (bahut common setup mistake), search() empty list dega — is se bachne ke
    liye retrieval_service ek brute_force_search() fallback bhi use karta hai
    jo bina kisi Atlas index ke, seedha Python me cosine similarity nikaal
    ke kaam karta hai.
    """

    def __init__(self, collection):
        # collection: motor ka AsyncIOMotorCollection, e.g. db[PPT_CHUNKS_COLLECTION]
        self.collection = collection

    async def link_exists(self, source_link: str) -> bool:
        """Check karo ki is PDF ke chunks pehle se DB me store hain ya nahi."""
        if not source_link:
            return False
        doc = await self.collection.find_one({"source_link": source_link}, {"_id": 1})
        return doc is not None

    async def count(self, source_link: Optional[str] = None) -> int:
        """Kitne chunk documents collection me hain (debugging / diagnostics ke liye)."""
        query = {"source_link": source_link} if source_link else {}
        return await self.collection.count_documents(query)

    async def add_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        """
        Pehle se text banaye hue chunk-dicts ko embed karke insert karta hai.
        Har dict me kam se kam "text" key honi chahiye; baaki (source_link,
        ppt_id, chunk_type, image_file_id, page_number) metadata ki tarah
        carry hoti hai.
        """
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = embed_texts(texts)

        docs = []
        for chunk, embedding in zip(chunks, embeddings):
            doc = dict(chunk)
            doc["embedding"] = embedding
            docs.append(doc)

        await self.collection.insert_many(docs)

    async def add_texts(self, chunks: List[str], source_link: Optional[str] = None) -> None:
        """Backward-compatible helper: plain text chunks (no extra metadata)."""
        await self.add_chunks([{"text": c, "source_link": source_link} for c in chunks])

    async def search(
        self,
        query: str,
        top_k: int = 3,
        source_link: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query se sabse milte-julte top_k chunks Atlas Vector Search se dhoondo.
        Har result me "text", "score" (cosine similarity), aur metadata
        (source_link, ppt_id, chunk_type, image_file_id, page_number) hote hain.

        Agar source_link diya gaya hai, to search sirf usi PDF ke chunks tak
        restrict rahega (filter field jo scripts/create_vector_index.py me
        define kiya gaya hai).

        NOTE: agar Atlas Vector Search index exist nahi karta, ya abhi
        "queryable" nahi hua (build ho raha hai), Atlas is stage se koi error
        nahi deta — bas 0 results wapas aate hain. Isliye empty result ka
        matlab "koi data nahi hai" nahi hota — retrieval_service isi wajah se
        empty result par brute_force_search() try karta hai.
        """
        query_embedding = embed_text(query)

        vector_search_stage = {
            "index": VECTOR_INDEX_NAME,
            "path": "embedding",
            "queryVector": query_embedding,
            "numCandidates": max(top_k * 10, 100),
            "limit": top_k,
        }
        if source_link:
            vector_search_stage["filter"] = {"source_link": {"$eq": source_link}}

        pipeline = [
            {"$vectorSearch": vector_search_stage},
            {
                "$project": {
                    "_id": 0,
                    "text": 1,
                    "source_link": 1,
                    "ppt_id": 1,
                    "chunk_type": 1,
                    "image_file_id": 1,
                    "page_number": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]

        try:
            cursor = self.collection.aggregate(pipeline)
            results = await cursor.to_list(length=top_k)
        except Exception:
            # Index missing/misnamed, or this isn't an Atlas cluster at all
            # (a local/self-hosted mongod doesn't support $vectorSearch).
            # Don't blow up the request — let the caller fall back to
            # brute_force_search() instead.
            results = []

        return results

    async def brute_force_search(
        self,
        query: str,
        top_k: int = 3,
        source_link: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Atlas Vector Search index ke bina bhi kaam karne wala search — sabhi
        (ya source_link se filtered) chunk documents Mongo se seedha fetch
        karke, har ek ke against query ka cosine similarity Python me nikalta
        hai. Chhote/medium collections ke liye theek hai; Atlas index jitna
        fast/scalable nahi hai, lekin kabhi bhi "silently zero results"
        nahi dega jab tak data actually collection me maujood hai.
        """
        query_vector = embed_text(query)

        mongo_query = {"source_link": source_link} if source_link else {}
        projection = {
            "text": 1,
            "embedding": 1,
            "source_link": 1,
            "ppt_id": 1,
            "chunk_type": 1,
            "image_file_id": 1,
            "page_number": 1,
        }

        cursor = self.collection.find(mongo_query, projection)
        docs = await cursor.to_list(length=None)

        scored = []
        for doc in docs:
            embedding = doc.get("embedding")
            if not embedding:
                continue
            score = cosine_similarity(query_vector, embedding)
            scored.append((score, doc))

        scored.sort(key=lambda pair: pair[0], reverse=True)

        results = []
        for score, doc in scored[:top_k]:
            results.append({
                "text": doc.get("text"),
                "source_link": doc.get("source_link"),
                "ppt_id": doc.get("ppt_id"),
                "chunk_type": doc.get("chunk_type"),
                "image_file_id": doc.get("image_file_id"),
                "page_number": doc.get("page_number"),
                "score": score,
            })
        return results


def get_ppt_vector_store(db) -> MongoVectorStore:
    """FastAPI routes me `request.app.mongodb` se DB milta hai — yeh helper
    seedha usi se PPT chunks collection ka vector store bana deta hai."""
    return MongoVectorStore(db[PPT_CHUNKS_COLLECTION])
