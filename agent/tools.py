"""
agent/tools.py
--------------
Agent tools that wrap the existing pipeline functions.

Each tool is a plain Python function that the LangGraph nodes call.
These are NOT LangChain tools — they're direct function calls.
LangGraph orchestrates WHEN to call them, not how.

Why not LangChain tools:
  "Signal detection is deterministic computation. I don't want an LLM
   deciding whether to compute PRR — I want it deciding whether the
   PRR result needs deeper investigation. The tools are fixed; the
   reasoning about their output is what's agentic."
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def tool_detect_signals(drug_name, date_end=None, top_n=50):
    """
    Tool 1: Run FAERS signal detection.
    Returns flagged signals sorted by composite score.
    """
    from signals.compute_signals import detect_signals
    signals = detect_signals(drug_name, date_end=date_end, top_n=top_n, enrich=False)
    flagged = [s for s in signals if s["flagged"]]
    return signals, flagged


def tool_fetch_label(drug_name):
    """
    Tool 2: Fetch FDA drug label sections from DailyMed.
    Returns dict of safety-relevant sections.
    """
    from data.fetch_label import fetch_label_sections
    return fetch_label_sections(drug_name)


def tool_check_label_gap(event_term, label_sections, drug_name=""):
    """
    Tool 3: Check if a flagged event is novel or already in the label.
    Returns {status, match_score, matched_section, matched_text, method}.
    """
    from signals.check_label_gap import check_label_gap
    return check_label_gap(event_term, label_sections, drug_name)


def tool_search_pubmed(drug_name, event_name, max_results=5):
    """
    Tool 4: Search PubMed for published evidence on drug+event.
    Returns list of article dicts.
    """
    from data.fetch_pubmed import search_drug_event
    return search_drug_event(drug_name, event_name, max_results=max_results)


def tool_search_pubmed_deep(drug_name, event_name, max_results=10):
    """
    Tool 5: Deeper PubMed search — more results, broader query.
    Used when initial search returns < 2 articles.
    This is the agent's "I need more information" action.
    """
    from data.fetch_pubmed import search_drug_event
    # First try with more results
    articles = search_drug_event(drug_name, event_name, max_results=max_results)

    # If still sparse, try broader terms
    if len(articles) < 3:
        # Try with drug class or mechanism terms
        broader = search_drug_event(drug_name, f"{event_name} risk safety", max_results=5)
        # Deduplicate by PMID
        seen_pmids = {a["pmid"] for a in articles}
        for a in broader:
            if a["pmid"] not in seen_pmids:
                articles.append(a)
                seen_pmids.add(a["pmid"])

    return articles


def tool_synthesize_report(signal, label_gap, pubmed_articles):
    """
    Tool 6: LLM synthesis — generate evidence-graded report.
    Returns structured report dict.
    """
    from rag.synthesize_report import synthesize_signal_report
    return synthesize_signal_report(signal, label_gap, pubmed_articles)


def tool_embed_evidence(drug_name, label_sections, pubmed_articles):
    """
    Tool 7: Embed label + PubMed into ChromaDB for retrieval.
    Called once per drug, then retrieval is fast.
    """
    from rag.embed_abstracts import embed_label_sections, embed_pubmed_articles
    n_label = embed_label_sections(drug_name, label_sections)
    n_pubmed = embed_pubmed_articles(drug_name, pubmed_articles)
    return n_label + n_pubmed
