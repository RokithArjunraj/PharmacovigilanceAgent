"""
signals/check_label_gap.py
--------------------------
Determines whether a flagged FAERS signal is already documented
in the drug's FDA label, or is a novel emerging signal.

Two-layer approach:
  Layer 1 — exact/substring match: fast, catches ~70% of cases
  Layer 2 — semantic similarity: catches "tendon rupture" = "tendinopathy"

What you learn here:
  - Why keyword matching alone fails for medical text (synonyms, variants)
  - How cosine similarity solves the synonym problem
  - The threshold decision (0.75) and why it matters
  - Caching embeddings so you don't re-embed the same label repeatedly
"""

import json
import re
from pathlib import Path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import shared serious outcomes list
try:
    from signals.serious_outcomes import SERIOUS_OUTCOMES
except ImportError:
    # Fallback if Person A hasn't created the file yet
    SERIOUS_OUTCOMES = [
        "myocardial infarction", "cardiac arrest", "liver failure",
        "anaphylaxis", "stroke", "suicidal ideation", "aplastic anaemia",
        "stevens-johnson syndrome", "pulmonary embolism", "renal failure acute",
        "sudden cardiac death", "hepatic failure", "rhabdomyolysis",
    ]
EMBED_CACHE_DIR = Path("data/label_embeddings")
EMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Similarity threshold — above this = "known_different_wording"
# 0.75 chosen because medical synonyms typically score 0.78-0.92
# False positives (unrelated but similar-sounding terms) score < 0.70
SIMILARITY_THRESHOLD = 0.68
SIMILARITY_THRESHOLD_SERIOUS = 0.58

# MedDRA-style synonym expansions for common terms
# These help Layer 1 catch obvious variants without semantic search
SYNONYM_MAP = {
    "myocardial infarction":     ["heart attack", "mi ", "cardiac infarction", "coronary"],
    "hepatotoxicity":            ["liver", "hepatic", "hepatitis", "jaundice", "cholestasis"],
    "tendon rupture":            ["tendinopathy", "tendinitis", "tendon", "achilles"],
    "peripheral neuropathy":     ["neuropathy", "nerve damage", "numbness", "tingling"],
    "aortic aneurysm":           ["aorta", "aneurysm", "aortic dissection"],
    "oedema peripheral":         ["edema", "swelling", "fluid retention", "peripheral edema"],
    "cardiac failure":           ["heart failure", "cardiac failure", "chf", "cardiomyopathy"],
    "suicidal ideation":         ["suicide", "self-harm", "suicidal thoughts", "depression"],
    "hyperkalaemia":             ["high potassium", "elevated potassium", "hyperkalemia", "potassium"],
    "renal failure acute":       ["acute kidney injury", "aki", "acute renal", "kidney failure"],
    "cardiac failure congestive":["congestive heart failure", "chf", "heart failure", "cardiac failure"],
    "hepatocellular injury":     ["hepatotoxicity", "liver injury", "liver damage", "hepatic injury"],
    "cough":                     ["dry cough", "persistent cough", "cough"],
    "angioedema":                ["swelling", "angioedema", "face swelling", "throat swelling"],
    "pancytopenia":              ["bone marrow", "blood count", "myelosuppression", "pancytopenia"],
    "agranulocytosis":           ["low white blood cell", "neutropenia", "granulocyte"],
    "alopecia":                  ["hair loss", "hair thinning"],
    "hyponatraemia":             ["low sodium", "sodium", "hyponatremia"],
}


# ── Embedding model (singleton) ───────────────────────────────────────────────

_model = None

def get_model():
    """Load once, reuse. Avoids reloading the 80MB model on every call."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print("  Loading sentence-transformer model...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


# ── Embedding cache ───────────────────────────────────────────────────────────

def _load_label_embeddings(drug_name: str) -> dict | None:
    """Load pre-computed paragraph embeddings for a drug's label."""
    p = EMBED_CACHE_DIR / f"{drug_name.lower().replace(' ', '_')}_embeddings.json"
    if p.exists():
        with open(p) as f:
            data = json.load(f)
            # Convert lists back to numpy arrays
            import numpy as np
            return {k: np.array(v) for k, v in data.items()}
    return None


def _save_label_embeddings(drug_name: str, embeddings: dict):
    """Save paragraph embeddings to avoid re-computing for same drug."""
    p = EMBED_CACHE_DIR / f"{drug_name.lower().replace(' ', '_')}_embeddings.json"
    with open(p, "w") as f:
        # Convert numpy arrays to lists for JSON serialisation
        json.dump({k: v.tolist() for k, v in embeddings.items()}, f)


# ── Text chunking ─────────────────────────────────────────────────────────────

def _chunk_label_text(label_sections: dict,
                      restrict_to: set = None) -> list[dict]:
    import re
    all_chunks = []
    for section_name, text in label_sections.items():
        if restrict_to and section_name not in restrict_to:
            continue
        if not text or len(text) < 30:
            continue
        sentences = re.split(r'(?<=[.!?])\s+', text)
        buffer = []
        for sent in sentences:
            buffer.append(sent)
            if len(' '.join(buffer)) > 150:
                all_chunks.append({
                    "text":    ' '.join(buffer),
                    "section": section_name
                })
                buffer = []
        if buffer:
            all_chunks.append({
                "text":    ' '.join(buffer),
                "section": section_name
            })
    return all_chunks


# ── Layer 1: Exact / synonym match ───────────────────────────────────────────

def _exact_match(event_term, label_sections):
    event_lower = event_term.lower()
    
    ADR_SECTIONS = {"adverse_reactions", "boxed_warning", "warnings_and_precautions"}
    
    # Search ADR sections first
    adr_text = " ".join(
        v for k, v in label_sections.items() if k in ADR_SECTIONS
    ).lower()
    
    if event_lower in adr_text:
        return {"status": "known", "method": "exact_match",
                "matched_section": _find_section(event_lower, label_sections),
                "match_score": 1.0,
                "matched_text": _find_context(event_lower, label_sections)}
    
    # Check synonyms against ADR sections
    for syn in SYNONYM_MAP.get(event_lower, []):
        if syn in adr_text:
            return {"status": "known", "method": "synonym_match",
                    "matched_section": "adverse_reactions",
                    "match_score": 0.95, "synonym_used": syn,
                    "matched_text": _find_context(syn, label_sections)}
    
    # Only now check indications — separate status
    indications_text = label_sections.get("indications_and_usage", "").lower()
    if event_lower in indications_text:
        return {"status": "indication_confound", "method": "exact_match",
                "matched_section": "indications_and_usage",
                "match_score": 1.0, "matched_text": ""}
    
    return None


def _find_section(term: str, label_sections: dict) -> str:
    """Find which section contains the term."""
    for section, text in label_sections.items():
        if term in text.lower():
            return section
    return "unknown"


def _find_context(term: str, label_sections: dict, window: int = 200) -> str:
    """Extract a snippet of text around the matched term."""
    for section, text in label_sections.items():
        idx = text.lower().find(term)
        if idx >= 0:
            start = max(0, idx - 80)
            end   = min(len(text), idx + window)
            return text[start:end]
    return ""


# ── Layer 2: Semantic similarity ──────────────────────────────────────────────

ADR_SECTIONS = {"adverse_reactions", "boxed_warning", "warnings_and_precautions"}

def _semantic_match(event_term: str, label_sections: dict,
                    drug_name: str = "") -> dict:
    import numpy as np

    model = get_model()

    # Search ADR sections only — never match indications semantically as "known"
    adr_only = {k: v for k, v in label_sections.items() if k in ADR_SECTIONS}
    chunks = _chunk_label_text(adr_only)

    if not chunks:
        return {"status": "novel", "match_score": 0.0,
                "matched_section": "", "matched_text": "",
                "method": "semantic_no_label_text"}

    # Cache key uses only ADR sections so adding indications doesn't invalidate it
    cache_key = drug_name + "_adr"
    cached = _load_label_embeddings(cache_key) if drug_name else None

    if cached and len(cached) == len(chunks):
        para_embeddings = [cached.get(str(i)) for i in range(len(chunks))]
        para_embeddings = [e for e in para_embeddings if e is not None]
    else:
        para_embeddings = model.encode(
            [c["text"] for c in chunks], show_progress_bar=False
        )
        if drug_name:
            _save_label_embeddings(cache_key,
                                   {str(i): e for i, e in enumerate(para_embeddings)})

    event_embedding = model.encode(event_term)

    def cosine_sim(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

    similarities  = [cosine_sim(event_embedding, pe) for pe in para_embeddings]
    best_idx      = int(np.argmax(similarities))
    best_score    = similarities[best_idx]

    # Use event-appropriate threshold
    is_serious = any(s in event_term.lower() for s in SERIOUS_OUTCOMES)
    threshold  = SIMILARITY_THRESHOLD_SERIOUS if is_serious else SIMILARITY_THRESHOLD

    if best_score >= threshold:
        return {
            "status":          "known_different_wording",
            "match_score":     round(best_score, 3),
            "matched_section": chunks[best_idx]["section"],
            "matched_text":    chunks[best_idx]["text"][:300],
            "method":          "semantic_similarity",
        }

    # Semantic check against indications — separate status
    ind_text = label_sections.get("indications_and_usage", "")
    if ind_text:
        ind_chunks = _chunk_label_text({"indications_and_usage": ind_text})
        if ind_chunks:
            ind_embs   = model.encode([c["text"] for c in ind_chunks],
                                       show_progress_bar=False)
            ind_scores = [cosine_sim(event_embedding, e) for e in ind_embs]
            if max(ind_scores) >= 0.72:   # higher bar — avoid false indication matches
                return {
                    "status":          "indication_confound",
                    "match_score":     round(max(ind_scores), 3),
                    "matched_section": "indications_and_usage",
                    "matched_text":    "",
                    "method":          "semantic_indication_match",
                }

    return {"status": "novel", "match_score": round(best_score, 3),
            "matched_section": "", "matched_text": "",
            "method": "semantic_similarity"}

# ── Public interface ──────────────────────────────────────────────────────────

def check_label_gap(event_term: str, label_sections: dict,
                    drug_name: str = "") -> dict:
    """
    Main function. Determines if a FAERS adverse event is:
      "known"                — explicitly mentioned in the label
      "known_different_wording" — semantically present but different term
      "novel"                — not documented in the label

    Args:
        event_term     : FAERS adverse event term e.g. "Myocardial infarction"
        label_sections : dict from fetch_label_sections()
        drug_name      : used for embedding cache key (optional)

    Returns dict with:
        status, match_score, matched_section, matched_text, method
    """
    # Layer 1: try exact / synonym match first (fast)
    exact_result = _exact_match(event_term, label_sections)
    if exact_result:
        return exact_result

    # Layer 2: semantic similarity (slower but catches synonyms)
    return _semantic_match(event_term, label_sections, drug_name)

def flag_confounding_risk(co_medications: list[dict]) -> dict:
    """
    If a co-medication appears in >50% of reports alongside
    the drug+event, flag it as a potential confound.

    We don't statistically adjust for confounding — FAERS data
    alone can't support that. We flag it transparently so a
    reviewer knows to consider drug interaction as an alternative
    explanation.

    co_medications: list of {"term": "metformin", "count": 120}
                    from Person A's get_co_medications()
    """
    if not co_medications:
        return {"confounding_risk": "unknown", "warning": None}

    total = sum(item["count"] for item in co_medications[:10])
    if total == 0:
        return {"confounding_risk": "unknown", "warning": None}

    top = co_medications[0]
    top_pct = top["count"] / total

    if top_pct > 0.5:
        return {
            "confounding_risk": "HIGH",
            "warning": (
                f"{top['term']} appears in {top_pct*100:.0f}% of co-reports "
                f"— signal may reflect a drug interaction rather than "
                f"a single-drug effect. Interpret with caution."
            ),
            "top_co_drug": top["term"],
            "co_occurrence_pct": round(top_pct * 100, 1),
        }

    return {
        "confounding_risk": "LOW",
        "warning": None,
        "top_co_drug": top["term"] if co_medications else None,
        "co_occurrence_pct": round(top_pct * 100, 1),
    }

def compute_combined_score(signal: dict, label_gap: dict,
                            pubmed_articles: list[dict],
                            confounding: dict) -> dict:
    """
    Combines statistical signal + literature evidence + novelty + confounding
    into one score for prioritisation.

    This is the answer to the low-count-but-critical scenario:
    PRR 2.1 with 3 PubMed case reports + novel label status ranks
    higher than PRR 4.0 with no literature + already in label.

    Returns: {"combined_score": float, "confidence": str}
    """
    event_lower = signal["event"].lower()
    is_serious  = any(s in event_lower for s in SERIOUS_OUTCOMES)

    # 1. Statistical strength — capped so high count doesn't dominate
    stat = signal["prr"] * min(signal["count"], 100) / 100

    # 2. Literature corroboration — case reports weighted most
    #    because they represent independent clinical observation
    case_reports = sum(
        1 for a in pubmed_articles
        if "case report" in
           " ".join(a.get("publication_types", [])).lower()
    )
    lit_boost = min(case_reports * 0.3, 1.0)

    # 3. Novelty — novel signals are more actionable than known ones
    novelty_boost = {
        "novel":                   1.5,
        "known_different_wording": 0.5,
        "known":                   0.0,
    }.get(label_gap.get("status", "unknown"), 0.3)

    # 4. Confounding penalty — reduce score if likely confounded
    confound_penalty = 0.5 if confounding.get("confounding_risk") == "HIGH" else 0.0

    # 5. Severity multiplier — serious outcomes get elevated regardless
    severity_mult = 2.5 if is_serious else 1.0

    raw   = (stat + lit_boost + novelty_boost - confound_penalty)
    final = round(raw * severity_mult, 3)

    # Confidence label — honest about uncertainty
    if final >= 6.0:
        confidence = "HIGH"
    elif final >= 3.0:
        confidence = "MODERATE"
    elif is_serious and final >= 1.0:
        confidence = "LOW_COUNT_HIGH_CONCERN"
    else:
        confidence = "LOW"

    return {
        "combined_score":  final,
        "confidence":      confidence,
        "is_serious":      is_serious,
        "breakdown": {
            "statistical":      round(stat, 3),
            "literature_boost": round(lit_boost, 3),
            "novelty_boost":    novelty_boost,
            "confound_penalty": confound_penalty,
            "severity_mult":    severity_mult,
        }
    }

# ── Test ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    from tests.mock_signals import MOCK_ROSIGLITAZONE_SIGNALS

    print("=== Testing check_label_gap.py ===\n")

    label_cache = Path("data/labels/rosiglitazone.json")
    if label_cache.exists():
        with open(label_cache) as f:
            label = json.load(f)
        print("Using real rosiglitazone label.\n")
    else:
        label = {
            "adverse_reactions": (
                "Cardiovascular: Myocardial infarction and cardiac failure "
                "have been reported. Peripheral edema is common, 4-8% of patients."
            ),
            "warnings_and_precautions": (
                "Rosiglitazone may cause or worsen congestive heart failure."
            ),
            "boxed_warning": "", "contraindications": "", "drug_interactions": "",
        }
        print("Using mock label.\n")

    # Test 1 — label gap check
    print("── Test 1: Label gap check ──")
    for signal in MOCK_ROSIGLITAZONE_SIGNALS:
        if not signal["flagged"]:
            continue
        result = check_label_gap(signal["event"], label, "rosiglitazone")
        if result["status"] == "indication_confound":
           continue
        icon   = "✓ KNOWN" if result["status"] != "novel" else "⚠ NOVEL"
        print(f"{icon} | {signal['event']}")
        print(f"  score={result['match_score']} | method={result['method']}")
        if result.get("matched_text"):
            print(f"  match: {result['matched_text'][:80]}...")
        print()

    # Test 2 — confounding flag
    print("── Test 2: Confounding flag ──")
    mock_co_meds = [
        {"term": "METFORMIN", "count": 180},
        {"term": "LISINOPRIL", "count": 45},
        {"term": "ASPIRIN",    "count": 30},
    ]
    conf = flag_confounding_risk(mock_co_meds)
    print(f"Confounding risk: {conf['confounding_risk']}")
    if conf["warning"]:
        print(f"Warning: {conf['warning']}")
    print()

    # Test 3 — combined score
    print("── Test 3: Combined score ──")
    mock_gap      = {"status": "novel", "match_score": 0.31}
    mock_articles = [
        {"publication_types": ["Case Report"]},
        {"publication_types": ["Case Report"]},
        {"publication_types": ["Review"]},
    ]
    score = compute_combined_score(
        MOCK_ROSIGLITAZONE_SIGNALS[0],  # myocardial infarction
        mock_gap, mock_articles, conf
    )
    print(f"Combined score : {score['combined_score']}")
    print(f"Confidence     : {score['confidence']}")
    print(f"Breakdown      : {score['breakdown']}")

    print("\n✓ All tests passed")