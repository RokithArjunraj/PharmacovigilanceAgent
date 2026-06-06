"""
rag/synthesize_report.py
-------------------------
LLM-powered evidence synthesis for flagged signals.

Takes: signal stats + label gap + PubMed abstracts
Returns: structured clinical intelligence report

Uses Groq API (llama-3.1-8b-instant) for fast, free inference.
Every LLM response is cached to avoid repeat calls.
"""

import json
import hashlib
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import GROQ_API_KEY, GROQ_MODEL

CACHE_DIR = Path("cache/llm")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Groq client ──────────────────────────────────────────────────

def _get_groq_client():
    from groq import Groq
    return Groq(api_key=GROQ_API_KEY)


def _cache_path(prompt_hash):
    return CACHE_DIR / f"{prompt_hash}.json"


def _call_llm(prompt, system_prompt=""):
    """
    Call Groq LLM with caching.
    Same prompt always returns same result — saves API calls during dev.
    """
    # Cache key from prompt content
    raw = system_prompt + prompt
    h = hashlib.md5(raw.encode()).hexdigest()
    cache = _cache_path(h)

    if cache.exists():
        with open(cache) as f:
            return json.load(f)["response"]

    client = _get_groq_client()
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.2,  # low temperature for factual consistency
            max_tokens=1000,
        )
        response = completion.choices[0].message.content

        # Cache the response
        with open(cache, "w") as f:
            json.dump({"prompt_hash": h, "response": response}, f, indent=2)

        return response

    except Exception as e:
        print(f"  [!] Groq API error: {e}")
        return None


# ── Prompt templates ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a pharmacovigilance scientist reviewing adverse event signals.
You provide factual, evidence-based assessments. You cite sources explicitly.
When evidence is insufficient, you say so clearly — never speculate.
Respond ONLY in valid JSON format with no additional text or markdown."""

SIGNAL_REPORT_PROMPT = """Analyze this drug safety signal and return a JSON assessment.

DRUG: {drug}
ADVERSE EVENT: {event}

STATISTICAL SIGNAL:
- PRR (Proportional Reporting Ratio): {prr}
- ROR (Reporting Odds Ratio): {ror}
- Chi-squared: {chi_squared}
- FAERS report count: {count}
- Evans' criteria met: Yes (flagged signal)

LABEL STATUS: {label_status}
Label match score: {label_match_score}
Label match detail: {label_match_detail}

PUBLISHED LITERATURE (PubMed abstracts):
{pubmed_evidence}

CRITICAL RULES:
- If fewer than 3 PubMed articles directly discuss this drug causing this event, evidence_grade CANNOT be "Strong". Use "Moderate" at most.
- If the mechanism is unknown or unclear, evidence_grade CANNOT be "Strong". Use "Weak" or "Moderate".
- If the PubMed articles mention the drug incidentally (patient was "also taking" the drug) rather than studying it as the cause, do NOT cite them as supporting evidence.
- Only grade as "Strong" when multiple independent studies or case reports specifically investigate this drug causing this event.

TASK: Based on the statistical signal, label status, and published evidence,
provide your assessment as JSON with exactly these fields:

{{
  "evidence_grade": "Strong" or "Moderate" or "Weak" or "Inconclusive",
  "mechanism": "Brief plausible biological mechanism (1-2 sentences). Say 'Unknown mechanism' if no evidence.",
  "clinical_significance": "What does this mean for patient safety? (1-2 sentences)",
  "recommendation": "What should a pharmacovigilance team do? (1-2 sentences)",
  "key_citations": ["PMID:xxxxx - brief description", ...],
  "confidence_reasoning": "Why this evidence grade? (1 sentence)",
  "is_actionable": true or false
}}"""

KNOWN_SIGNAL_PROMPT = """This adverse event is ALREADY DOCUMENTED in the FDA-approved drug label.
Your job is to confirm it, not discover it.

DRUG: {drug}
ADVERSE EVENT: {event}

STATISTICAL SIGNAL:
- PRR: {prr}
- FAERS report count: {count}

LABEL DOCUMENTATION:
Section: {label_section}
Relevant text: {label_text}

This is a KNOWN, LABELED adverse event. Respond as JSON:

{{
  "evidence_grade": "Confirmed",
  "mechanism": "Brief mechanism from label text. Say 'See product label' if not clear from the text.",
  "clinical_significance": "This is a documented adverse event with PRR {prr} indicating current reporting rate. (1 sentence)",
  "recommendation": "Continue routine pharmacovigilance monitoring. (1 sentence)",
  "key_citations": ["FDA-approved product label, {label_section} section"],
  "confidence_reasoning": "Event is documented in the FDA-approved label",
  "is_actionable": false
}}"""

ABSTENTION_PROMPT = """Analyze this drug-event pair where evidence is LIMITED.

DRUG: {drug}
ADVERSE EVENT: {event}
PRR: {prr} (count: {count})
Label status: {label_status}
PubMed articles found: {pubmed_count}

The statistical signal exists but literature evidence is sparse.
Should this be escalated or marked as inconclusive?

Respond as JSON:
{{
  "evidence_grade": "Weak" or "Inconclusive",
  "recommendation": "Specific next step (1 sentence)",
  "abstention_reason": "Why evidence is insufficient (1 sentence)",
  "is_actionable": false,
  "needs_followup": true or false
}}"""


# ── Main synthesis function ──────────────────────────────────────

def synthesize_signal_report(signal, label_gap, pubmed_articles):
    """
    Generate an LLM-powered evidence report for a flagged signal.

    Args:
        signal: dict from compute_signals.py
            {drug, event, count, prr, ror, chi_squared, flagged, ...}
        label_gap: dict from check_label_gap.py
            {status, match_score, matched_section, matched_text, method}
        pubmed_articles: list of dicts from fetch_pubmed.py
            [{pmid, title, abstract, authors, year, ...}, ...]

    Returns:
        dict with evidence_grade, mechanism, recommendation, citations, etc.
        Returns None if LLM call fails.
    """
    drug = signal["drug"]
    event = signal["event"]

    print(f"  Synthesizing report: {drug} + {event}...")

    # Build the PubMed evidence section for the prompt
    if pubmed_articles:
        evidence_parts = []
        for i, article in enumerate(pubmed_articles[:5], 1):
            abstract_preview = article.get("abstract", "")[:400]
            evidence_parts.append(
                f"[{i}] PMID:{article.get('pmid', 'N/A')} "
                f"({article.get('year', 'N/A')}) — {article.get('title', 'No title')}\n"
                f"    {abstract_preview}..."
            )
        pubmed_text = "\n\n".join(evidence_parts)
    else:
        pubmed_text = "No relevant PubMed articles found."

    # Decide which prompt to use
    if label_gap.get("status") in ["known", "known_different_wording"]:
        # KNOWN SIGNAL — use label-based prompt, skip PubMed entirely
        prompt = KNOWN_SIGNAL_PROMPT.format(
            drug=drug,
            event=event,
            prr=signal["prr"],
            count=signal["count"],
            label_section=label_gap.get("matched_section", "adverse_reactions"),
            label_text=label_gap.get("matched_text", "See product label")[:500],
        )
    elif len(pubmed_articles) < 2 and label_gap.get("status") == "novel":
        # NOVEL + THIN EVIDENCE — use abstention prompt
        prompt = ABSTENTION_PROMPT.format(
            drug=drug,
            event=event,
            prr=signal["prr"],
            count=signal["count"],
            label_status=label_gap.get("status", "unknown"),
            pubmed_count=len(pubmed_articles),
        )
    else:
        # NOVEL + SUFFICIENT EVIDENCE — use full report prompt
        prompt = SIGNAL_REPORT_PROMPT.format(
            drug=drug,
            event=event,
            prr=signal["prr"],
            ror=signal["ror"],
            chi_squared=signal["chi_squared"],
            count=signal["count"],
            label_status=label_gap.get("status", "unknown"),
            label_match_score=label_gap.get("match_score", "N/A"),
            label_match_detail=label_gap.get("matched_text", "")[:200],
            pubmed_evidence=pubmed_text,
        )

    # Call LLM
    response = _call_llm(prompt, SYSTEM_PROMPT)
    if not response:
        return None

    # Parse JSON response
    try:
        # Strip markdown fences if present
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            clean = clean.rsplit("```", 1)[0]
        report = json.loads(clean)
    except json.JSONDecodeError:
        print(f"    [!] Failed to parse LLM response as JSON")
        print(f"    Raw response: {response[:200]}...")
        report = {
            "evidence_grade": "Parse Error",
            "mechanism": response[:200],
            "recommendation": "Manual review required — LLM output was not valid JSON",
            "is_actionable": False,
        }

    # Post-LLM grade correction — enforce evidence rules
    grade = report.get("evidence_grade", "")
    mechanism = report.get("mechanism", "")
    
    # Rule 1: Cannot be Strong with fewer than 3 PubMed articles
    if grade == "Strong" and len(pubmed_articles) < 3:
        report["evidence_grade"] = "Moderate"
        report["grade_adjusted"] = "Downgraded: fewer than 3 directly supporting articles"
    
    # Rule 2: Cannot be Strong with unknown mechanism
    mechanism_lower = mechanism.lower()
    if grade == "Strong" and any(
        phrase in mechanism_lower 
        for phrase in ["unclear", "unknown", "not fully understood", 
                       "not well established", "exact mechanism"]
    ):
        report["evidence_grade"] = "Weak"
        report["grade_adjusted"] = "Downgraded: mechanism unknown or unclear"
    
    # Rule 3: Cannot be Strong for abstained signals
    if report.get("abstained"):
        report["evidence_grade"] = "Inconclusive"    

    # Attach metadata
    report["drug"] = drug
    report["event"] = event
    report["prr"] = signal["prr"]
    report["label_status"] = label_gap.get("status", "unknown")
    report["pubmed_count"] = len(pubmed_articles)

    return report


# ── Batch synthesis ──────────────────────────────────────────────

def synthesize_all_signals(drug_name, flagged_signals, label_sections,
                           max_signals=10):
    """
    Run full synthesis pipeline for a drug's flagged signals.

    For each flagged signal:
      1. Check label gap (novel vs known)
      2. Search PubMed for corroboration
      3. Generate LLM evidence report

    Args:
        drug_name: generic drug name
        flagged_signals: list of signal dicts from compute_signals
        label_sections: dict from fetch_label.py
        max_signals: cap on how many signals to synthesize (LLM calls are slow)

    Returns:
        List of report dicts, one per signal.
    """
    from signals.check_label_gap import check_label_gap
    from data.fetch_pubmed import search_drug_event

    reports = []
    signals_to_process = flagged_signals[:max_signals]

    print(f"\n{'='*60}")
    print(f"Evidence Synthesis: {drug_name} ({len(signals_to_process)} signals)")
    print(f"{'='*60}")

    for i, signal in enumerate(signals_to_process, 1):
        event = signal["event"]
        print(f"\n  [{i}/{len(signals_to_process)}] {event} (PRR={signal['prr']})")

        # Step 1: Check label gap
        gap = check_label_gap(event, label_sections, drug_name)
        print(f"    Label: {gap['status']} (score={gap['match_score']})")

        # Step 2: Get PubMed evidence
        articles = search_drug_event(drug_name, event, max_results=5)
        print(f"    PubMed: {len(articles)} articles found")

        # Step 3: LLM synthesis
        report = synthesize_signal_report(signal, gap, articles)
        if report:
            reports.append(report)
            grade = report.get("evidence_grade", "?")
            actionable = report.get("is_actionable", False)
            print(f"    Grade: {grade} | Actionable: {actionable}")
        else:
            print(f"    [!] Synthesis failed")

    return reports


def print_synthesis_report(drug_name, reports):
    """Pretty-print the synthesis results."""
    print(f"\n{'='*65}")
    print(f"SIGNAL INTELLIGENCE REPORT: {drug_name}")
    print(f"{'='*65}")

    if not reports:
        print("No reports generated.")
        return

    # Sort by evidence grade
    grade_order = {"Strong": 0, "Moderate": 1, "Weak": 2, "Inconclusive": 3}
    reports.sort(key=lambda r: grade_order.get(r.get("evidence_grade", ""), 4))

    for i, r in enumerate(reports, 1):
        novel_tag = " [NOVEL]" if r.get("label_status") == "novel" else ""
        print(f"\n  [{i}] {r['event']}{novel_tag}")
        print(f"      PRR: {r.get('prr', '?')} | Grade: {r.get('evidence_grade', '?')}")
        print(f"      PubMed hits: {r.get('pubmed_count', 0)}")

        if r.get("mechanism"):
            print(f"      Mechanism: {r['mechanism'][:120]}")
        if r.get("clinical_significance"):
            print(f"      Significance: {r['clinical_significance'][:120]}")
        if r.get("recommendation"):
            print(f"      Action: {r['recommendation'][:120]}")
        if r.get("abstention_reason"):
            print(f"      Abstention: {r['abstention_reason'][:120]}")
        if r.get("key_citations"):
            for cite in r["key_citations"][:3]:
                print(f"      Cite: {cite[:80]}")

    # Summary counts
    novel = sum(1 for r in reports if r.get("label_status") == "novel")
    strong = sum(1 for r in reports if r.get("evidence_grade") == "Strong")
    actionable = sum(1 for r in reports if r.get("is_actionable"))

    print(f"\n  SUMMARY: {len(reports)} signals analysed")
    print(f"    Novel: {novel} | Strong evidence: {strong} | Actionable: {actionable}")


# ── Test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    from signals.compute_signals import detect_signals
    from data.fetch_label import fetch_label_sections

    print("Testing synthesize_report.py with rosiglitazone\n")

    # Step 1: Get signals
    signals = detect_signals("rosiglitazone", top_n=25, enrich=False)
    flagged = [s for s in signals if s["flagged"]][:5]

    # Step 2: Get label
    label = fetch_label_sections("rosiglitazone")

    # Step 3: Synthesize
    reports = synthesize_all_signals("rosiglitazone", flagged, label, max_signals=5)

    # Step 4: Display
    print_synthesis_report("rosiglitazone", reports)

    print("\n✓ synthesize_report.py working")