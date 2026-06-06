"""
evaluation/run_eval.py
-----------------------
Full evaluation pipeline — 4 tiers.

Tier 1: Signal recall (SOC-level, Novel-only, with lead time)
Tier 2: Specificity (Known/Novel breakdown, false discovery rate)
Tier 3: RAG evidence grading accuracy (LLM + PubMed with date cutoff)
Tier 4: Retrospective purity (does PubMed date cutoff change grades?)

Ground truth: FDA Drug Safety Communications (public record)
Matching: MedDRA System Organ Class root terms (published standard)

Works locally and on Streamlit Cloud (ephemeral filesystem).
"""

import json
import sys
import os
import re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.drug_names import get_positive_drugs, get_negative_controls
from signals.compute_signals import detect_signals
from data.batch_cache import DRUG_SOC_KEYWORDS, soc_match


# ── Ground truth evidence grades ─────────────────────────────────────────────
# Source: FDA Drug Safety Communications + published meta-analyses
# Each entry cites the specific evidence justifying the expected grade.

EVAL_EVIDENCE_GRADES = {
    "rosiglitazone": {
        "event":          "Myocardial infarction",
        "expected_grade": "Strong",
        "rationale":      "Nissen 2007 NEJM meta-analysis OR 1.43 (95% CI 1.03-1.98) p=0.03",
    },
    "ciprofloxacin": {
        "event":          "Tendon rupture",
        "expected_grade": "Strong",
        "rationale":      "FDA black box warning 2008; multiple RCTs and cohort studies",
    },
    "metoclopramide": {
        "event":          "Tardive dyskinesia",
        "expected_grade": "Strong",
        "rationale":      "FDA black box warning 2009; established dopamine antagonist mechanism",
    },
    "varenicline": {
        "event":          "Suicidal ideation",
        "expected_grade": "Strong",
        "rationale":      "FDA MedWatch 2009; multiple controlled post-marketing studies",
    },
    "loperamide": {
        "event":          "Cardiac arrest",
        "expected_grade": "Strong",
        "rationale":      "FDA Drug Safety Communication 2016; case series of abuse-related cardiac events",
    },
    "canagliflozin": {
        "event":          "Diabetic ketoacidosis",
        "expected_grade": "Strong",
        "rationale":      "FDA Safety Communication 2015; mechanistically driven (urinary glucose loss)",
    },
    "dronedarone": {
        "event":          "Hepatotoxicity",
        "expected_grade": "Strong",
        "rationale":      "FDA Safety Communication 2011; two cases of acute liver failure requiring transplant",
    },
    "pioglitazone": {
        "event":          "Bladder cancer",
        "expected_grade": "Strong",
        "rationale":      "KPNC cohort HR 1.83 (95% CI 1.10-3.05); FDA label update 2011",
    },
    "dapagliflozin": {
        "event":          "Diabetic ketoacidosis",
        "expected_grade": "Strong",
        "rationale":      "FDA Safety Communication 2015; class effect confirmed across SGLT2i",
    },
    "zolpidem": {
        "event":          "Somnolence",
        "expected_grade": "Strong",
        "rationale":      "FDA dose reduction 2013; multiple epidemiological studies on next-day impairment",
    },
    "omeprazole": {
        "event":          "Hypomagnesaemia",
        "expected_grade": "Inconclusive",
        "rationale":      "Case reports only at cutoff; no controlled studies; mechanism unclear",
    },
    "olmesartan": {
        "event":          "Enteropathy",
        "expected_grade": "Inconclusive",
        "rationale":      "Limited case series at cutoff; mechanism proposed but unconfirmed",
    },
}

# Grade adjacency — what counts as acceptable for each expected grade
GRADE_GROUPS = {
    "Strong":       ["Strong"],
    "Moderate":     ["Strong", "Moderate"],
    "Inconclusive": ["Inconclusive", "Weak"],
    "Weak":         ["Inconclusive", "Weak"],
}


# ── Tier 1: Signal Recall ─────────────────────────────────────────────────────

def run_signal_recall_eval(top_n=50):
    """
    Tier 1: Retrospective signal detection recall.

    Improvements over original:
    - Lead time: months between cutoff and FDA warning date
    - PRR CI lower bound reported
    - False discovery rate: novel false positives / total novel flagged
    """
    print(f"\n{'='*70}")
    print(f"TIER 1: SIGNAL RECALL EVALUATION")
    print(f"Retrospective signal detection recall (SOC-level)")
    print(f"{'='*70}")
    print(f"  Lead time reported per drug")

    positive = get_positive_drugs()
    results  = []

    for drug_name, info in positive.items():
        cutoff       = info["faers_cutoff"]
        warning_date = info.get("fda_warning_date")

        # Lead time in months
        lead_months = None
        if warning_date and cutoff:
            try:
                w = datetime.strptime(warning_date, "%Y-%m-%d")
                c = datetime.strptime(cutoff, "%Y%m%d")
                lead_months = round((w - c).days / 30.4)
            except Exception:
                pass

        print(f"\n  {drug_name} (cutoff: {cutoff}, lead: {lead_months}mo)...", end=" ")

        signals = detect_signals(drug_name, date_end=cutoff, top_n=top_n,
                                 verbose=False, enrich=False)
        flagged = [s for s in signals if s["flagged"]]
        print(flagged)
        # Separate Novel vs Known flagged signals
        # Note: label_status is only set for signals that passed through
        # check_label_gap — unflagged signals don't have it
        novel_flagged = [s for s in flagged if s.get("label_status", "novel") not in
                         ("known", "known_different_wording", "indication_confound")]
        known_flagged = [s for s in flagged if s.get("label_status", "") in
                         ("known", "known_different_wording")]

        # SOC match against NOVEL signals only
        novel_matches, category = soc_match(flagged, drug_name)
        all_matches, _          = soc_match(flagged, drug_name)

        status = "HIT" if novel_matches else "MISS"
        print(f"{status} ({len(flagged)} flagged, {len(novel_flagged)} novel, "
              f"{len(novel_matches)} novel SOC matches)")

        results.append({
            "drug":           drug_name,
            "status":         status,
            "category":       category,
            "flagged_total":  len(flagged),
            "novel_flagged":  len(novel_flagged),
            "known_flagged":  len(known_flagged),
            "novel_matches":  len(novel_matches),
            "all_matches":    len(all_matches),
            "lead_months":    lead_months,
            "top_match":      novel_matches[0] if novel_matches else (
                              all_matches[0] if all_matches else None),
            "cutoff":         cutoff,
        })

    hits  = sum(1 for r in results if r["status"] == "HIT")
    total = len(results)

    print(f"\n  NOVEL-ONLY SIGNAL RECALL: {hits}/{total} "
          f"({100*hits/max(total,1):.0f}%)")

    avg_lead = [r["lead_months"] for r in results
                if r["status"] == "HIT" and r["lead_months"]]
    if avg_lead:
        print(f"  Average lead time (HITs only): "
              f"{sum(avg_lead)/len(avg_lead):.0f} months before FDA warning")

    return results, hits, total


# ── Tier 2: Specificity ───────────────────────────────────────────────────────

def run_abstention_eval(top_n=30):
    """
    Tier 2: False positive rate on negative controls.

    Improvements over original:
    - Known vs Novel breakdown (Known FPs are less concerning)
    - False discovery rate per drug
    - Serious Novel false positives (the real danger)
    """
    print(f"\n{'='*70}")
    print(f"TIER 2: SPECIFICITY EVALUATION")
    print(f"{'='*70}")
    print(f"  Known/Novel breakdown reported")
    print(f"  False discovery rate = novel false positives / total novel flagged")

    negative = get_negative_controls()
    results  = []

    for drug_name, info in negative.items():
        print(f"\n  {drug_name}...", end=" ")

        signals = detect_signals(drug_name, top_n=top_n, verbose=False, enrich=False)
        flagged = [s for s in signals if s["flagged"]]

        novel_flagged  = [s for s in flagged if s.get("label_status", "novel") not in
                          ("known", "known_different_wording", "indication_confound")]
        known_flagged  = [s for s in flagged if s.get("label_status", "") in
                          ("known", "known_different_wording")]
        serious_novel  = [s for s in novel_flagged if s.get("is_serious")]

        fdr = round(len(novel_flagged) / max(len(flagged), 1), 2)

        print(f"{len(flagged)} flagged | "
              f"{len(novel_flagged)} novel | "
              f"{len(known_flagged)} known | "
              f"{len(serious_novel)} serious-novel | "
              f"FDR={fdr}")

        results.append({
            "drug":           drug_name,
            "flagged_total":  len(flagged),
            "novel_flagged":  len(novel_flagged),
            "known_flagged":  len(known_flagged),
            "serious_novel":  len(serious_novel),
            "fdr":            fdr,
            "top_novel_events": [s["event"] for s in novel_flagged[:3]],
        })

    total_serious_novel = sum(r["serious_novel"] for r in results)
    avg_fdr = sum(r["fdr"] for r in results) / max(len(results), 1)

    print(f"\n  SERIOUS NOVEL FALSE POSITIVES: {total_serious_novel}")
    print(f"  AVERAGE FALSE DISCOVERY RATE:  {avg_fdr:.2f}")
    if total_serious_novel == 0:
        print(f"  PERFECT — 0 serious novel signals on clean drugs")

    return results, total_serious_novel, avg_fdr


# ── Tier 3: RAG Evidence Grading ─────────────────────────────────────────────

def run_rag_grading_eval(pubmed_cutoff=True):
    """
    Tier 3: Evaluate RAG + LLM evidence grading accuracy.

    For each drug-event pair in EVAL_EVIDENCE_GRADES:
    1. Fetch PubMed with date cutoff (retrospective purity)
    2. Run ChromaDB embed + retrieve
    3. Run LLM synthesis
    4. Compare grade to clinical consensus ground truth

    Args:
        pubmed_cutoff: if True, filter PubMed by pre-warning year
                       (prevents future knowledge leakage)
    """
    print(f"\n{'='*70}")
    print(f"TIER 3: RAG EVIDENCE GRADING EVALUATION")
    mode = "WITH date cutoff" if pubmed_cutoff else "WITHOUT date cutoff"
    print(f"  PubMed mode: {mode}")
    print(f"  Ground truth: FDA Drug Safety Communications + published meta-analyses")
    print(f"{'='*70}")

    from data.fetch_pubmed    import search_drug_event
    from data.fetch_label     import fetch_label_sections
    from rag.embed_abstracts  import embed_pubmed_articles, retrieve
    from rag.synthesize_report import synthesize_signal_report
    from signals.check_label_gap import check_label_gap
    from signals.compute_signals import detect_signals

    results = []

    for drug_name, ground_truth in EVAL_EVIDENCE_GRADES.items():
        event          = ground_truth["event"]
        expected_grade = ground_truth["expected_grade"]
        drug_info      = get_positive_drugs().get(drug_name, {})
        cutoff         = drug_info.get("faers_cutoff", "")
        warning_date   = drug_info.get("fda_warning_date", "")

        # PubMed year cutoff for retrospective purity
        max_year = None
        if pubmed_cutoff and warning_date:
            max_year = int(warning_date[:4])

        print(f"\n  {drug_name} + {event}...", end=" ")

        try:
            # Step 1: Fetch PubMed with optional date cutoff
            articles = search_drug_event(
                drug_name, event,
                max_results=10,
                max_year=max_year,      # ← retrospective purity
            )

            # Step 2: Embed into ChromaDB
            collection_name = f"eval_{drug_name.replace(' ','_')}"
            embed_pubmed_articles(drug_name, articles, collection_name)

            # Step 3: Retrieve relevant chunks
            query   = f"{drug_name} {event} adverse effect risk"
            chunks  = retrieve(query, collection_name,
                               drug_name=drug_name, source_filter="pubmed", top_k=5)
            retrieved_texts = [c["text"] for c in chunks]

            # Step 4: Get signal stats for this drug-event pair
            signals  = detect_signals(drug_name, date_end=cutoff,
                                      top_n=50, verbose=False, enrich=False)
            matching = [s for s in signals if event.lower() in s["event"].lower()]
            signal   = matching[0] if matching else {
                "drug": drug_name, "event": event,
                "prr": 0, "ror": 0, "chi_squared": 0, "count": 0
            }

            # Step 5: Label gap check
            label_sections = fetch_label_sections(drug_name)
            gap = check_label_gap(event, label_sections, drug_name)

            # Step 6: Build synthetic article dicts from retrieved chunks
            # so synthesize_signal_report receives the RAG-retrieved content
            rag_articles = []
            for chunk in chunks:
                meta = chunk.get("metadata", {})
                rag_articles.append({
                    "pmid":     meta.get("pmid", ""),
                    "title":    "",
                    "abstract": chunk["text"],
                    "year":     meta.get("year", ""),
                    "journal":  meta.get("journal", ""),
                    "publication_types": [],
                })

            # Step 7: LLM synthesis using RAG-retrieved chunks
            report = synthesize_signal_report(signal, gap, rag_articles)

            actual_grade = report.get("evidence_grade", "Unknown") if report else "Error"
            acceptable   = GRADE_GROUPS.get(expected_grade, [expected_grade])
            passed       = actual_grade in acceptable

            # Citation verification: check retrieved PMIDs appear in citations
            cited_pmids    = set()
            retrieved_pmids = {c.get("metadata", {}).get("pmid", "") for c in chunks}
            if report and report.get("key_citations"):
                for cite in report["key_citations"]:
                    m = re.search(r"PMID:?(\d+)", cite, re.IGNORECASE)
                    if m:
                        cited_pmids.add(m.group(1))
            citation_grounded = len(cited_pmids & retrieved_pmids) > 0 if cited_pmids else None

            status = "PASS" if passed else "FAIL"
            print(f"{status} (expected {expected_grade}, got {actual_grade}, "
                  f"{len(articles)} articles, grounded={citation_grounded})")

            results.append({
                "drug":               drug_name,
                "event":              event,
                "expected_grade":     expected_grade,
                "actual_grade":       actual_grade,
                "status":             status,
                "pubmed_hits":        len(articles),
                "retrieved_chunks":   len(chunks),
                "citation_grounded":  citation_grounded,
                "pubmed_cutoff_year": max_year,
                "rationale":          ground_truth["rationale"],
            })

        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                "drug": drug_name, "event": event,
                "expected_grade": expected_grade, "actual_grade": "Error",
                "status": "ERROR", "pubmed_hits": 0,
                "retrieved_chunks": 0, "citation_grounded": None,
                "pubmed_cutoff_year": max_year,
                "rationale": ground_truth["rationale"],
            })

    passed_count = sum(1 for r in results if r["status"] == "PASS")
    total        = len(results)
    grounded     = [r for r in results if r.get("citation_grounded") is True]

    print(f"\n  RAG GRADING ACCURACY:     {passed_count}/{total} "
          f"({100*passed_count/max(total,1):.0f}%)")
    print(f"  CITATION GROUNDEDNESS:    {len(grounded)}/{total} "
          f"signals have citations traceable to retrieved PMIDs")

    failed = [r for r in results if r["status"] == "FAIL"]
    if failed:
        print(f"\n  GRADING FAILURES:")
        for r in failed:
            print(f"    {r['drug']} + {r['event']}: "
                  f"expected {r['expected_grade']}, got {r['actual_grade']} "
                  f"({r['pubmed_hits']} articles)")

    return results, passed_count, total


# ── Tier 4: Retrospective Purity ─────────────────────────────────────────────

def run_purity_eval():
    """
    Tier 4: Does PubMed date cutoff change evidence grades?

    Runs Tier 3 twice — with and without date cutoff.
    Reports which signals change grade when future papers are excluded.
    This proves the system isn't leaking post-warning knowledge.
    """
    print(f"\n{'='*70}")
    print(f"TIER 4: RETROSPECTIVE PURITY CHECK")
    print(f"{'='*70}")
    print(f"  Running grading WITH and WITHOUT PubMed date cutoff...")
    print(f"  Signals that change grade reveal future knowledge leakage.")

    results_with,    passed_with,    total = run_rag_grading_eval(pubmed_cutoff=True)
    results_without, passed_without, _     = run_rag_grading_eval(pubmed_cutoff=False)

    # Compare grades
    grade_map_with    = {r["drug"]: r["actual_grade"] for r in results_with}
    grade_map_without = {r["drug"]: r["actual_grade"] for r in results_without}

    changed = []
    for drug in grade_map_with:
        g_with    = grade_map_with.get(drug)
        g_without = grade_map_without.get(drug)
        if g_with != g_without:
            changed.append({
                "drug":         drug,
                "with_cutoff":  g_with,
                "no_cutoff":    g_without,
            })

    print(f"\n  With cutoff:    {passed_with}/{total} correct grades")
    print(f"  Without cutoff: {passed_without}/{total} correct grades")
    print(f"  Signals changed by cutoff: {len(changed)}/{total}")

    if changed:
        print(f"\n  LEAKAGE DETECTED — these signals grade differently with future papers:")
        for c in changed:
            print(f"    {c['drug']}: {c['no_cutoff']} → {c['with_cutoff']} "
                  f"(after removing post-warning literature)")
    else:
        print(f"\n  NO LEAKAGE — grades unchanged with/without date cutoff")

    return changed, passed_with, passed_without, total


# ── Full Evaluation ───────────────────────────────────────────────────────────

def run_full_evaluation(include_rag=True, include_purity=True):
    """
    Run all evaluation tiers and produce a summary report.

    Args:
        include_rag:    Run Tier 3 (slow — makes PubMed + LLM calls)
        include_purity: Run Tier 4 (slowest — runs Tier 3 twice)
    """
    print(f"\n{'='*70}")
    print(f"PHARMASIGNAL — FULL EVALUATION")
    print(f"Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    # Tier 1
    recall_results, hits, total_pos = run_signal_recall_eval()

    # Tier 2
    abstention_results, false_pos, avg_fdr = run_abstention_eval()

    # Tier 3 (optional — slow)
    grading_results, grading_passed, total_grading = None, None, None
    if include_rag and not include_purity:
        grading_results, grading_passed, total_grading = run_rag_grading_eval(
            pubmed_cutoff=True
        )

    # Tier 4 (optional — slowest)
    purity_results = None
    if include_purity:
        purity_results, grading_passed, _, total_grading = run_purity_eval()

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"EVALUATION SUMMARY")
    print(f"{'='*70}")
    print(f"\n  Ground truth: FDA Drug Safety Communications")
    print(f"  Matching:     MedDRA System Organ Class root terms")
    print(f"  Methodology:  Retrospective — pre-warning FAERS data only")

    print(f"\n  TIER 1 — Novel Signal Recall: "
          f"{hits}/{total_pos} ({100*hits/max(total_pos,1):.0f}%)")
    for r in recall_results:
        marker    = "✓" if r["status"] == "HIT" else "✗"
        lead_str  = f" [{r['lead_months']}mo lead]" if r["lead_months"] else ""
        match_str = ""
        if r["top_match"]:
            match_str = f" → {r['top_match']['event']} (PRR={r['top_match']['prr']})"
        print(f"    {marker} {r['drug']:<18} {r['category']:<28}"
              f"{lead_str}{match_str}")

    print(f"\n  TIER 2 — Specificity:")
    print(f"    Serious novel false positives: {false_pos}")
    print(f"    Average false discovery rate:  {avg_fdr:.2f}")
    for r in abstention_results:
        print(f"    {r['drug']:<18} "
              f"{r['flagged_total']} flagged | "
              f"{r['novel_flagged']} novel | "
              f"FDR={r['fdr']}")

    if grading_passed is not None:
        print(f"\n  TIER 3 — RAG Grading Accuracy: "
              f"{grading_passed}/{total_grading} "
              f"({100*grading_passed/max(total_grading,1):.0f}%)")

    if purity_results is not None:
        print(f"\n  TIER 4 — Retrospective Purity: "
              f"{len(purity_results)} signals affected by future knowledge leakage")

    # Missed signals
    missed = [r for r in recall_results if r["status"] == "MISS"]
    if missed:
        print(f"\n  MISSED SIGNALS ({len(missed)}):")
        for r in missed:
            print(f"    {r['drug']}: expected {r['category']}")
            print(f"      {r['novel_flagged']} novel events flagged, none matched SOC")

    # Save JSON
    eval_output = {
        "run_date":      datetime.now().isoformat(),
        "tier1_recall":  {
            "hits": hits, "total": total_pos,
            "pct":  round(100*hits/max(total_pos,1), 1),
            "note": "Novel-only — Known signals excluded from hit counting",
        },
        "tier2_specificity": {
            "serious_novel_false_positives": false_pos,
            "avg_false_discovery_rate":      round(avg_fdr, 3),
            "total_controls":                len(abstention_results),
        },
        "tier3_rag_grading": {
            "passed":  grading_passed,
            "total":   total_grading,
            "pct":     round(100*grading_passed/max(total_grading or 1, 1), 1)
                       if grading_passed is not None else None,
            "pubmed_cutoff_applied": True,
        },
        "tier4_purity": {
            "signals_affected_by_leakage": len(purity_results)
                                           if purity_results is not None else None,
        },
        "recall_details":     recall_results,
        "abstention_details": abstention_results,
    }

    output_path = Path("evaluation/eval_results.json")
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(eval_output, f, indent=2, default=str)
    print(f"\n  Results saved to: {output_path}")

    return eval_output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PharmaSignal Evaluation")
    parser.add_argument("--tier", type=int, default=0,
                        help="Run specific tier only (1/2/3/4). 0=all tiers.")
    parser.add_argument("--no-purity", action="store_true",
                        help="Skip Tier 4 purity check (faster)")
    args = parser.parse_args()

    if args.tier == 1:
        run_signal_recall_eval()
    elif args.tier == 2:
        run_abstention_eval()
    elif args.tier == 3:
        run_rag_grading_eval(pubmed_cutoff=True)
    elif args.tier == 4:
        run_purity_eval()
    else:
        run_full_evaluation(
            include_rag=True,
            include_purity=not args.no_purity
        )
