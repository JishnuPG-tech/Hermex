import os
import re
import math
import sqlite3
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from hermes_core.tools.registry import registry

DB_PATH = Path(os.getenv("HERMES_MEMORY_DB", "/data/hermes/memory.sqlite"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# 1. Vector Store & Episodic Schema Initialization
def _init_memory_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodic_memory (
            key TEXT PRIMARY KEY,
            value TEXT,
            category TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS semantic_vector_store (
            id TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            chunk_content TEXT,
            token_vector TEXT,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

_init_memory_db()

# 2. Ultra-Fast Embedded Vector & Tokenizer Engine
def _tokenize_and_vectorize(text: str) -> Dict[str, float]:
    """Generates an L2-normalized term-frequency vector with sub-word n-gram features."""
    if not text:
        return {}
    
    clean = re.sub(r'[^\w\s]', ' ', text.lower())
    words = clean.split()
    if not words:
        return {}

    tf: Dict[str, float] = {}
    for w in words:
        if len(w) > 2:
            tf[w] = tf.get(w, 0.0) + 1.0

    for w in words:
        if len(w) >= 3:
            for i in range(len(w) - 2):
                ngram = f"#{w[i:i+3]}"
                tf[ngram] = tf.get(ngram, 0.0) + 0.5

    norm = math.sqrt(sum(v * v for v in tf.values()))
    if norm > 0:
        return {k: round(v / norm, 4) for k, v in tf.items()}
    return tf

def _cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Calculates cosine similarity between two normalized sparse vectors."""
    if not vec_a or not vec_b:
        return 0.0
    common_keys = set(vec_a.keys()) & set(vec_b.keys())
    return sum(vec_a[k] * vec_b[k] for k in common_keys)

def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
    """Splits long text documents into overlapping semantic chunks."""
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            next_break = text.rfind("\n", start, end)
            if next_break > start + 200:
                end = next_break + 1
        chunks.append(text[start:end].strip())
        start += chunk_size - overlap
    return chunks

# 3. Public Vector Store Interface
def index_document_vector(source: str, title: str, content: str, metadata: Optional[Dict[str, Any]] = None):
    """Indexes a document into the persistent semantic vector store."""
    if not content or not content.strip():
        return
    
    chunks = _chunk_text(content.strip(), chunk_size=600, overlap=120)
    conn = sqlite3.connect(DB_PATH)
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)

    for idx, ch in enumerate(chunks):
        doc_id = f"{source}_{abs(hash(title))}_{idx}"
        vec = _tokenize_and_vectorize(ch)
        vec_json = json.dumps(vec, ensure_ascii=False)
        conn.execute(
            "INSERT OR REPLACE INTO semantic_vector_store (id, source, title, chunk_content, token_vector, metadata) VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, source, title, ch, vec_json, meta_json)
        )
    conn.commit()
    conn.close()

def search_semantic_memory(query: str, top_k: int = 4, threshold: float = 0.12) -> List[Dict[str, Any]]:
    """Performs hybrid semantic similarity search across indexed vectors and memories."""
    q_vec = _tokenize_and_vectorize(query)
    if not q_vec:
        return []

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, source, title, chunk_content, token_vector, metadata FROM semantic_vector_store")
    rows = cur.fetchall()
    conn.close()

    scored_results = []
    for row in rows:
        doc_id, source, title, chunk_content, vec_json, meta_json = row
        try:
            doc_vec = json.loads(vec_json)
            score = _cosine_similarity(q_vec, doc_vec)
            if score >= threshold:
                meta = json.loads(meta_json) if meta_json else {}
                scored_results.append({
                    "id": doc_id,
                    "source": source,
                    "title": title,
                    "content": chunk_content,
                    "score": round(score, 3),
                    "metadata": meta
                })
        except Exception:
            continue

    scored_results.sort(key=lambda x: x["score"], reverse=True)
    return scored_results[:top_k]

# 4. Registered Hermes Agent Tools
@registry.register(
    name="memory_store",
    description="Save important facts, user preferences, project context, or knowledge into long-term semantic memory.",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Unique key or topic title"},
            "value": {"type": "string", "description": "Fact, code snippet, or memory content to store"},
            "category": {"type": "string", "description": "Category (e.g. 'user_preference', 'project_fact', 'architecture')"}
        },
        "required": ["key", "value"]
    },
    category="memory"
)
def memory_store(key: str, value: str, category: str = "general") -> str:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO episodic_memory (key, value, category) VALUES (?, ?, ?)", (key, value, category))
    conn.commit()
    conn.close()

    index_document_vector(
        source=f"memory_{category}",
        title=key,
        content=f"Topic: {key}\nCategory: {category}\nDetails: {value}",
        metadata={"category": category, "key": key}
    )
    return f"Successfully saved and vector-indexed memory for '{key}'."

@registry.register(
    name="memory_recall",
    description="Recall stored facts, user preferences, past conversations, or code snippets using hybrid semantic vector search.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Topic, question, or keyword to search in semantic memory"}
        },
        "required": ["query"]
    },
    category="memory"
)
def memory_recall(query: str) -> str:
    vector_matches = search_semantic_memory(query, top_k=4)
    if vector_matches:
        formatted = []
        for m in vector_matches:
            formatted.append(f"[{m['title']} (Score: {m['score']})]:\n{m['content']}")
        return "\n\n".join(formatted)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT key, value, category FROM episodic_memory WHERE key LIKE ? OR value LIKE ? LIMIT 5", (f"%{query}%", f"%{query}%"))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return f"No memories found matching '{query}'."
    return json.dumps([{"key": r[0], "value": r[1], "category": r[2]} for r in rows], ensure_ascii=False)
