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
Respond ONLY in valid JSON format with no additional text or markdown.

EVIDENCE GRADING CRITERIA (use these definitions exactly):

STRONG — Any ONE of the following is sufficient:
  - A meta-analysis, systematic review, or large cohort study showing statistically significant association
  - Multiple independent case reports/series specifically investigating this drug causing this event
  - A PRR >= 10 with >= 50 FAERS reports AND at least one published study (any design) supporting the association
  - A known pharmacological mechanism that directly explains the adverse event (e.g. NAPQI pathway for paracetamol hepatotoxicity)
  - An FDA Drug Safety Communication, boxed warning, or REMS related to this event

MODERATE — The signal has supporting evidence but falls short of Strong:
  - A single well-designed study (cohort or case-control) with significant findings
  - Multiple case reports with a plausible but unconfirmed mechanism
  - PRR >= 5 with >= 30 FAERS reports and at least one relevant publication
  - Biological plausibility based on drug class effects (e.g. all SGLT2 inhibitors and DKA)

WEAK — Limited evidence that does not rule out the association:
  - Only isolated case reports with no clear mechanism
  - Published articles mention the drug incidentally but do not investigate the causal link
  - PRR is elevated but case count is low (< 20 reports)

INCONCLUSIVE — Cannot assess the relationship:
  - Zero relevant PubMed articles AND no known pharmacological basis
  - Available literature contradicts the association
  - Signal is likely confounded (e.g. the event is the disease being treated)

IMPORTANT: A very high PRR (>= 10) with substantial case count (>= 50) is itself strong statistical evidence.
Do not default to Weak or Inconclusive when the disproportionality signal is overwhelming."""

SIGNAL_REPORT_PROMPT = """Analyze this drug safety signal and return a JSON assessment.

DRUG: {drug}
ADVERSE EVENT: {event}

STATISTICAL SIGNAL:
- PRR (Proportional Reporting Ratio): {prr}
- ROR (Reporting Odds Ratio): {ror}
- Chi-squared: {chi_squared}
- FAERS report count: {count}
- Evans' criteria met: Yes (flagged signal)

PRR INTERPRETATION:
- PRR 2-5: modest disproportionality, could be noise or confounding
- PRR 5-10: notable disproportionality, warrants investigation
- PRR 10-50: strong disproportionality, hard to explain by chance alone
- PRR > 50: extreme disproportionality, very strong statistical evidence of association

LABEL STATUS: {label_status}
Label match score: {label_match_score}
Label match detail: {label_match_detail}

PUBLISHED LITERATURE (PubMed abstracts):
{pubmed_evidence}

ARTICLE RELEVANCE CHECK:
Before citing any article, verify it DIRECTLY discusses {drug} causing or being associated with {event}.
Discard articles that:
- Only mention {drug} as a co-medication the patient was taking
- Study a different drug in the same class without mentioning {drug} specifically
- Discuss {event} in a completely different therapeutic context

GRADING GUIDANCE:
- Use the EVIDENCE GRADING CRITERIA from your system instructions
- Statistical signal strength (PRR, count) is REAL evidence — a PRR of {prr} with {count} reports is not to be dismissed
- A very strong statistical signal (PRR >= 10, count >= 50) combined with even a single supporting study can justify "Strong"
- Do NOT default to conservative grades when evidence converges from multiple sources (statistics + literature + mechanism)

TASK: Based on the statistical signal, label status, and published evidence,
provide your assessment as JSON with exactly these fields:

{{
  "evidence_grade": "Strong" or "Moderate" or "Weak" or "Inconclusive",
  "mechanism": "Brief plausible biological mechanism (1-2 sentences). Say 'Unknown mechanism' if no evidence.",
  "clinical_significance": "What does this mean for patient safety? (1-2 sentences)",
  "recommendation": "What should a pharmacovigilance team do? (1-2 sentences)",
  "key_citations": ["PMID:12345678 - brief description of finding", ...],
  "confidence_reasoning": "Why this evidence grade? Mention the statistical signal strength alongside literature. (1-2 sentences)",
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

ABSTENTION_PROMPT = """Analyze this drug-event pair where published literature evidence is LIMITED.

DRUG: {drug}
ADVERSE EVENT: {event}
PRR: {prr} (count: {count})
Label status: {label_status}
PubMed articles found: {pubmed_count}

The statistical signal exists in FAERS but few or no PubMed articles were found.

IMPORTANT: A strong statistical signal IS evidence, even without published literature.
- If PRR >= 10 and count >= 50, this is a strong disproportionality signal that warrants at least "Moderate"
- If PRR >= 5 and count >= 20, this warrants at least "Weak" with a recommendation for urgent literature review
- If PRR < 5 or count < 20, mark as "Inconclusive" pending further data

Respond as JSON:
{{
  "evidence_grade": "Moderate" or "Weak" or "Inconclusive",
  "mechanism": "Any known pharmacological basis, or 'Unknown mechanism' if none.",
  "recommendation": "Specific next step for the pharmacovigilance team (1 sentence)",
  "abstention_reason": "Why literature evidence is insufficient (1 sentence)",
  "clinical_significance": "Potential impact on patient safety based on the statistical signal (1 sentence)",
  "key_citations": [],
  "confidence_reasoning": "Grade justification considering statistical signal strength (1 sentence)",
  "is_actionable": true or false,
  "needs_followup": true
}}"""


# ── Article relevance filter ────────────────────────────────────

def _filter_relevant_articles(drug, event, articles):
    """
    Filter PubMed articles to only those that directly discuss
    the drug-event pair. Removes tangentially related articles
    that mention the drug incidentally or study a different condition.

    Returns (relevant_articles, discarded_count)
    """
    drug_lower = drug.lower()
    event_words = set(event.lower().replace("-", " ").split())
    # Remove generic words that appear everywhere
    stopwords = {"of", "the", "a", "an", "in", "to", "and", "with", "by", "for", "or", "not"}
    event_words -= stopwords

    relevant = []
    for article in articles:
        text = (
            article.get("title", "") + " " + article.get("abstract", "")
        ).lower()

        # Check 1: drug name must appear in text
        has_drug = drug_lower in text

        # Check 2: at least half the event words must appear
        matching_words = sum(1 for w in event_words if w in text)
        has_event = matching_words >= max(len(event_words) // 2, 1)

        if has_drug and has_event:
            relevant.append(article)

    discarded = len(articles) - len(relevant)
    if discarded > 0:
        print(f"    Relevance filter: kept {len(relevant)}/{len(articles)} articles "
              f"(discarded {discarded} tangentially related)")

    return relevant, discarded


# ── Main synthesis function ──────────────────────────────────────

def synthesize_signal_report(signal, label_gap, pubmed_articles, date_end=None):
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

    # Filter articles to only those directly relevant to this drug-event pair
    pubmed_articles, discarded = _filter_relevant_articles(drug, event, pubmed_articles)

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
        if discarded > 0:
            pubmed_text = (
                f"No directly relevant PubMed articles found "
                f"({discarded} tangentially related articles were excluded)."
            )
        else:
            pubmed_text = "No relevant PubMed articles found."

    # RETROSPECTIVE MODE: treat all signals as novel
    # Current label has future information (warnings added after cutoff)
    if date_end:
        label_gap = {**label_gap, "status": "novel"}

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
    elif len(pubmed_articles) == 0 and label_gap.get("status") == "novel":
        # NOVEL + ZERO LITERATURE — use abstention prompt (but it still considers PRR)
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
    prr = signal.get("prr", 0)
    count = signal.get("count", 0)

    # ── Relevance-based downgrade ──────────────────────────────────
    # If ZERO relevant articles AND no known mechanism AND weak stats → cap at Weak
    mechanism_lower = mechanism.lower()
    has_unknown_mechanism = any(
        phrase in mechanism_lower
        for phrase in ["unknown mechanism", "no direct evidence",
                       "no clear explanation", "no evidence linking"]
    )

    if grade == "Strong" and len(pubmed_articles) == 0 and has_unknown_mechanism:
        report["evidence_grade"] = "Moderate"
        report["grade_adjusted"] = "Downgraded: no literature and unknown mechanism"

    # ── PRR-based floor grade (upgrade path) ──────────────────────
    # Extreme statistical signals should not be graded below Moderate
    grade = report.get("evidence_grade", "")
    if prr >= 10 and count >= 50:
        if grade in ("Weak", "Inconclusive"):
            report["evidence_grade"] = "Moderate"
            report["grade_adjusted"] = (
                f"Upgraded from {grade}: PRR={prr:.1f} with {count} reports "
                f"is strong statistical evidence"
            )

    # Overwhelming statistical signal with ANY literature → Strong floor
    if prr >= 20 and count >= 100 and len(pubmed_articles) >= 1:
        grade = report.get("evidence_grade", "")
        if grade in ("Weak", "Inconclusive", "Moderate"):
            report["evidence_grade"] = "Strong"
            report["grade_adjusted"] = (
                f"Upgraded from {grade}: PRR={prr:.1f} with {count} reports "
                f"plus {len(pubmed_articles)} supporting article(s)"
            )

    # ── Abstention flag ──────────────────────────────────────────
    if report.get("abstained"):
        # Even abstained signals respect the PRR floor
        if prr < 10 or count < 50:
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
                           max_signals=10, date_end=None):
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
        articles = search_drug_event(drug_name, event, max_results=5, date_end=date_end)
        print(f"    PubMed: {len(articles)} articles found")

        # Step 3: LLM synthesis
        report = synthesize_signal_report(signal, gap, articles, date_end=date_end)
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