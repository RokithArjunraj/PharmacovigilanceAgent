import os

try:
    from streamlit import secrets as _s
    _secrets = dict(_s)
except Exception:
    _secrets = {}

def _get(key, default=None):
    return _secrets.get(key) or os.getenv(key) or default

# ── API endpoints ──
FAERS_BASE_URL = "https://api.fda.gov/drug/event.json"

# ── API keys ──
GROQ_API_KEY = _get("GROQ_API_KEY", "your_groq_api_key_here")
GROQ_MODEL   = _get("GROQ_MODEL", "llama-3.1-8b-instant")

# ── Cache directories ──
FAERS_CACHE_DIR   = "cache/faers"
LABEL_CACHE_DIR   = "cache/labels"
PUBMED_CACHE_DIR  = "cache/pubmed"
LLM_CACHE_DIR     = "cache/llm"

# ── Model settings ──
CHROMA_COLLECTION = "pharma_evidence"
EMBEDDING_MODEL   = "all-MiniLM-L6-v2"

# ── Signal detection thresholds (Evans' criteria) ──
PRR_THRESHOLD        = 2.0
CHI_SQUARED_THRESHOLD = 4.0
MIN_REPORT_COUNT     = 3

# ── Semantic similarity ──
SIMILARITY_THRESHOLD  = 0.75
LABEL_MATCH_THRESHOLD = 0.75

# ── Rate limits ──
PUBMED_RATE_LIMIT = 0.35
FAERS_RATE_LIMIT  = 0.3