"""
rag/embed_abstracts.py
----------------------
Shared embedding + ChromaDB infrastructure.
Used by both the label gap checker and the LLM evidence synthesis.

Same pattern as your interview RAG project — but now metadata carries
drug name, source (pubmed/label), and section so the LLM can cite properly.

What you learn here:
  - Reusing the same RAG infrastructure for different data types
  - Why metadata on chunks matters for citation and filtering
  - Singleton pattern for the embedding model (load once, reuse)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CHROMA_DIR = Path("data/chroma_db")
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

_model      = None
_chroma_client = None


# ── Singleton model ───────────────────────────────────────────────────────────

def get_embedding_model():
    """Load once, reuse. Same model as interview RAG project."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print("  Loading embedding model (all-MiniLM-L6-v2)...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _chroma_client


# ── Core functions ────────────────────────────────────────────────────────────

def embed_and_store(texts: list[str], metadatas: list[dict],
                    collection_name: str, reset: bool = False) -> int:
    """
    Embed texts and store in ChromaDB collection.

    Args:
        texts           : list of text strings to embed
        metadatas       : list of dicts — one per text. Include at minimum:
                          {"drug": "rosiglitazone", "source": "pubmed", "pmid": "12345"}
                          or {"drug": "rosiglitazone", "source": "label", "section": "adverse_reactions"}
        collection_name : ChromaDB collection name
        reset           : if True, delete and recreate the collection

    Returns:
        Number of chunks stored
    """
    if not texts:
        return 0

    model  = get_embedding_model()
    client = get_chroma_client()

    if reset:
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
    )

    # Generate unique IDs from metadata
    ids = []
    for i, meta in enumerate(metadatas):
        drug   = meta.get("drug", "unknown").replace(" ", "_")
        source = meta.get("source", "unknown")
        suffix = meta.get("pmid", meta.get("section", str(i)))
        ids.append(f"{drug}_{source}_{suffix}_{i}")

    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    # ChromaDB requires metadata values to be str/int/float/bool — no lists
    clean_meta = []
    for m in metadatas:
        clean_meta.append({
            k: (", ".join(v) if isinstance(v, list) else v)
            for k, v in m.items()
        })

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=clean_meta,
    )

    return len(texts)


def retrieve(query: str, collection_name: str,
             drug_name: str | None = None,
             source_filter: str | None = None,
             top_k: int = 5) -> list[dict]:
    """
    Retrieve top-k relevant chunks for a query.

    Args:
        query           : natural language query
        collection_name : ChromaDB collection to search
        drug_name       : optional — filter to this drug only
        source_filter   : optional — "pubmed" or "label"
        top_k           : number of chunks to return

    Returns:
        List of dicts with: text, metadata, similarity_score
    """
    model  = get_embedding_model()
    client = get_chroma_client()

    try:
        collection = client.get_collection(collection_name)
    except Exception:
        return []

    # Build where clause — same fix as interview RAG project
    filters = {}
    if drug_name:
        filters["drug"] = drug_name
    if source_filter:
        filters["source"] = source_filter

    if len(filters) == 0:
        where_clause = None
    elif len(filters) == 1:
        where_clause = filters
    else:
        where_clause = {"$and": [{k: v} for k, v in filters.items()]}

    query_embedding = model.encode(query).tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        where=where_clause,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        chunks.append({
            "text":       doc,
            "metadata":   meta,
            "similarity": round(1 - dist, 3),
        })

    return chunks


def embed_pubmed_articles(drug_name: str, articles: list[dict],
                          collection_name: str = "pharma_evidence") -> int:
    """
    Convenience function — embed PubMed articles for a drug.
    Splits each article into: title chunk + abstract chunk.
    """
    texts     = []
    metadatas = []

    for article in articles:
        # Title as one chunk
        if article.get("title"):
            texts.append(article["title"])
            metadatas.append({
                "drug":    drug_name,
                "source":  "pubmed",
                "pmid":    article.get("pmid", ""),
                "year":    article.get("year", ""),
                "type":    "title",
                "journal": article.get("journal", "")[:100],
            })

        # Abstract as one chunk
        if article.get("abstract"):
            # Determine evidence quality tier
            pub_types_str = " ".join(
                article.get("publication_types", [])
            ).lower()
            if "meta-analysis" in pub_types_str or "systematic review" in pub_types_str:
                evidence_tier = "tier1_meta_analysis"
            elif "clinical trial" in pub_types_str or "randomized" in pub_types_str:
                evidence_tier = "tier2_clinical_trial"
            elif "case report" in pub_types_str:
                evidence_tier = "tier3_case_report"
            else:
                evidence_tier = "tier4_other"

            texts.append(article["abstract"])
            metadatas.append({
                "drug":          drug_name,
                "source":        "pubmed",
                "pmid":          article.get("pmid", ""),
                "year":          article.get("year", ""),
                "type":          "abstract",
                "journal":       article.get("journal", "")[:100],
                "evidence_tier": evidence_tier,   # ← new field
            })

    return embed_and_store(texts, metadatas, collection_name)


def embed_label_sections(drug_name: str, label_sections: dict,
                         collection_name: str = "pharma_evidence") -> int:
    """
    Convenience function — embed label sections for a drug.
    Splits each section into paragraph-sized chunks.
    """
    import re
    texts     = []
    metadatas = []

    for section_name, text in label_sections.items():
        if not text or len(text) < 30:
            continue
        paragraphs = re.split(r"(?<=[.!?])\s{2,}|\n{2,}", text)
        for para in paragraphs:
            para = para.strip()
            if len(para) > 40:
                texts.append(para)
                metadatas.append({
                    "drug":    drug_name,
                    "source":  "label",
                    "section": section_name,
                    "pmid":    "",
                    "year":    "",
                    "type":    "label_paragraph",
                    "journal": "",
                })

    return embed_and_store(texts, metadatas, collection_name)


# ── Test ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Testing embed_abstracts.py ===\n")

    # Test with minimal mock data
    test_texts = [
        "Rosiglitazone is associated with increased risk of myocardial infarction.",
        "Cardiovascular mortality was higher in patients receiving rosiglitazone.",
        "Peripheral edema occurred in 4.8% of patients treated with rosiglitazone.",
        "Hepatotoxicity has not been observed in clinical trials of rosiglitazone.",
        "Lactic acidosis is a rare but serious complication of metformin therapy.",
    ]
    test_meta = [
        {"drug": "rosiglitazone", "source": "pubmed", "pmid": "1", "year": "2007", "type": "abstract", "journal": "NEJM"},
        {"drug": "rosiglitazone", "source": "pubmed", "pmid": "2", "year": "2008", "type": "abstract", "journal": "JAMA"},
        {"drug": "rosiglitazone", "source": "label",  "pmid": "", "year": "",     "type": "label_paragraph", "journal": ""},
        {"drug": "rosiglitazone", "source": "label",  "pmid": "", "year": "",     "type": "label_paragraph", "journal": ""},
        {"drug": "metformin",     "source": "label",  "pmid": "", "year": "",     "type": "label_paragraph", "journal": ""},
    ]

    n = embed_and_store(test_texts, test_meta, "test_collection", reset=True)
    print(f"Stored {n} chunks\n")

    print("Query: 'cardiovascular risk rosiglitazone'")
    results = retrieve("cardiovascular risk rosiglitazone",
                       "test_collection", drug_name="rosiglitazone", top_k=3)
    for r in results:
        print(f"  [{r['similarity']}] {r['text'][:80]}...")
        print(f"  source={r['metadata']['source']}\n")

    print("✓ embed_abstracts.py working")
