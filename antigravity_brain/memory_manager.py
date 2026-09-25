import os
import json
import datetime
import math
import sqlite3
from google import genai

DB_PATH = "/data/memory.db"
# Local fallback for dev/testing outside the addon container
if not os.path.exists("/data") and os.path.exists(os.path.dirname(__file__)):
    DB_PATH = os.path.join(os.path.dirname(__file__), "memory.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS memories
                 (id INTEGER PRIMARY KEY, fact TEXT, timestamp DATETIME, embedding TEXT)''')
    conn.commit()
    conn.close()

def _get_embedding(text, api_key):
    client = genai.Client(api_key=api_key)
    res = client.models.embed_content(
        model='gemini-embedding-2',
        contents=text
    )
    # Handling google-genai response object
    if hasattr(res, 'embeddings') and res.embeddings:
        if hasattr(res.embeddings[0], 'values'):
            return res.embeddings[0].values
        return res.embeddings[0]
    return []

def cosine_similarity(v1, v2):
    if not v1 or not v2: return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = math.sqrt(sum(a * a for a in v1))
    norm_v2 = math.sqrt(sum(b * b for b in v2))
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)

def store_memory(fact, api_key):
    try:
        embedding = _get_embedding(fact, api_key)
        if not embedding:
            return "Failed to generate embedding."
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO memories (fact, timestamp, embedding) VALUES (?, ?, ?)",
                  (fact, datetime.datetime.now().isoformat(), json.dumps(embedding)))
        conn.commit()
        conn.close()
        return "Memory stored successfully."
    except Exception as e:
        return f"Failed to store memory: {e}"

def search_memories(query, api_key, top_k=3):
    try:
        query_emb = _get_embedding(query, api_key)
        if not query_emb:
            return []
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT fact, embedding FROM memories")
        rows = c.fetchall()
        conn.close()

        results = []
        for fact, emb_str in rows:
            emb = json.loads(emb_str)
            sim = cosine_similarity(query_emb, emb)
            if sim >= 0.6:
                results.append((sim, fact))
        
        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:top_k]]
    except Exception as e:
        print(f"Error searching memories: {e}")
        return []
