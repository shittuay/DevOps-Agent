"""
Memory / Context Persistence Service

Stores and retrieves per-user memory entries that persist across conversations.
Uses TF-IDF for lightweight semantic search without external vector databases.
"""

import re
import math
import logging
from collections import Counter
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Simple stopwords for TF-IDF
STOPWORDS = {
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'can', 'shall', 'to', 'of', 'in', 'for',
    'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during',
    'before', 'after', 'above', 'below', 'between', 'out', 'off', 'over',
    'under', 'again', 'further', 'then', 'once', 'and', 'but', 'or', 'nor',
    'not', 'so', 'very', 'just', 'about', 'up', 'down', 'if', 'it', 'its',
    'my', 'your', 'his', 'her', 'our', 'their', 'this', 'that', 'these',
    'those', 'i', 'me', 'we', 'you', 'he', 'she', 'they', 'them', 'what',
    'which', 'who', 'whom', 'when', 'where', 'why', 'how', 'all', 'each',
    'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
    'only', 'own', 'same', 'than', 'too', 'also',
}


def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase words, filtering stopwords."""
    words = re.findall(r'[a-z0-9]+', text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def _cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Compute cosine similarity between two sparse vectors."""
    keys = set(vec_a.keys()) & set(vec_b.keys())
    if not keys:
        return 0.0

    dot = sum(vec_a[k] * vec_b[k] for k in keys)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _tfidf_vector(tokens: List[str], doc_count: int, doc_freq: Dict[str, int]) -> Dict[str, float]:
    """Compute TF-IDF vector for a list of tokens."""
    tf = Counter(tokens)
    max_tf = max(tf.values()) if tf else 1
    vec = {}
    for term, count in tf.items():
        tf_score = count / max_tf
        idf = math.log((doc_count + 1) / (doc_freq.get(term, 0) + 1)) + 1
        vec[term] = tf_score * idf
    return vec


def store_memory(db, user_id: int, content: str, category: str = 'general',
                 source: str = 'agent', importance: int = 5) -> Dict[str, Any]:
    """
    Store a new memory entry for a user.

    Args:
        db: SQLAlchemy database instance
        user_id: User ID
        content: Memory content text
        category: Category (general, preference, infrastructure, incident)
        source: Source (agent, user, system)
        importance: Importance 1-10

    Returns:
        Dict with stored memory info
    """
    from models import UserMemory

    memory = UserMemory(
        user_id=user_id,
        content=content,
        category=category,
        source=source,
        importance=min(max(importance, 1), 10),
    )
    db.session.add(memory)
    db.session.commit()

    logger.info(f"Stored memory for user {user_id}: {content[:80]}...")
    return memory.to_dict()


def search_memories(db, user_id: int, query: str, limit: int = 5,
                    category: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search user memories using TF-IDF similarity.

    Args:
        db: SQLAlchemy database instance
        user_id: User ID
        query: Search query text
        limit: Max results to return
        category: Optional category filter

    Returns:
        List of matching memories sorted by relevance
    """
    from models import UserMemory

    filters = [UserMemory.user_id == user_id, UserMemory.is_active == True]
    if category:
        filters.append(UserMemory.category == category)

    memories = UserMemory.query.filter(*filters).all()

    if not memories:
        return []

    # Build document frequency index
    doc_freq = Counter()
    doc_tokens = []
    for mem in memories:
        tokens = _tokenize(mem.content)
        doc_tokens.append(tokens)
        for term in set(tokens):
            doc_freq[term] += 1

    doc_count = len(memories)
    query_tokens = _tokenize(query)
    query_vec = _tfidf_vector(query_tokens, doc_count, doc_freq)

    # Score each memory
    scored = []
    for i, mem in enumerate(memories):
        doc_vec = _tfidf_vector(doc_tokens[i], doc_count, doc_freq)
        sim = _cosine_similarity(query_vec, doc_vec)
        # Boost by importance
        boosted = sim * (1 + (mem.importance - 5) * 0.1)
        if sim > 0.05:
            scored.append((boosted, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m.to_dict() for _, m in scored[:limit]]


def get_context_for_conversation(db, user_id: int, message: str,
                                 max_entries: int = 5) -> str:
    """
    Get relevant memory context to inject into a conversation.

    Args:
        db: SQLAlchemy database instance
        user_id: User ID
        message: Current user message to match against

    Returns:
        Formatted context string for system prompt injection
    """
    results = search_memories(db, user_id, message, limit=max_entries)

    if not results:
        return ""

    lines = ["Relevant context from previous interactions:"]
    for mem in results:
        lines.append(f"- [{mem['category']}] {mem['content']}")

    return "\n".join(lines)


def auto_extract_memories(db, user_id: int, message: str, response: str):
    """
    Automatically extract and store memorable facts from a conversation turn.
    Looks for infrastructure details, preferences, and decisions.
    """
    from models import UserMemory

    patterns = [
        (r'(?:my|our)\s+(?:aws|azure|gcp)\s+account\s+(?:id|number)?\s*(?:is|:)\s*(\S+)', 'infrastructure'),
        (r'(?:using|use|prefer)\s+(us-east-1|us-west-2|eu-west-1|ap-southeast-1|[\w-]+-\d)', 'preference'),
        (r'(?:production|prod)\s+(?:is|runs?\s+on|uses?)\s+(.{10,60})', 'infrastructure'),
        (r'(?:always|never|prefer)\s+(.{10,60})', 'preference'),
    ]

    for pattern, category in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            fact = match.group(0).strip()
            # Check if we already have this
            existing = UserMemory.query.filter(
                UserMemory.user_id == user_id,
                UserMemory.content.contains(fact[:30]),
                UserMemory.is_active == True,
            ).first()

            if not existing:
                store_memory(db, user_id, fact, category=category,
                             source='auto', importance=6)


def list_memories(db, user_id: int, category: Optional[str] = None,
                  limit: int = 50) -> List[Dict[str, Any]]:
    """List all active memories for a user."""
    from models import UserMemory

    query = UserMemory.query.filter_by(user_id=user_id, is_active=True)
    if category:
        query = query.filter_by(category=category)

    memories = query.order_by(UserMemory.importance.desc(), UserMemory.updated_at.desc()).limit(limit).all()
    return [m.to_dict() for m in memories]


def delete_memory(db, user_id: int, memory_id: int) -> bool:
    """Soft-delete a memory entry."""
    from models import UserMemory

    memory = UserMemory.query.filter_by(id=memory_id, user_id=user_id).first()
    if memory:
        memory.is_active = False
        db.session.commit()
        return True
    return False
