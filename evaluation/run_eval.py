"""
evaluation/run_eval.py
-----------------------
Full evaluation pipeline.

Three tiers:
  1. Signal recall (SOC-level) — did we catch the right organ-system signal?
  2. Abstention accuracy — did we stay quiet on clean drugs?
  3. RAG quality — is the LLM faithful to retrieved evidence?

Ground truth: FDA Drug Safety Communications (public record)
Matching: MedDRA System Organ Class root terms (published standard)
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.drug_names import get_positive_drugs, get_negative_controls
from signals.compute_signals import detect_signals
from data.batch_cache import DRUG_SOC_KEYWORDS, soc_match


def run_signal_recall_eval(top_n=50):
    """
    Tier 1: For each positive drug, run retrospective signal detection.
    Check if any flagged event matches the expected SOC category.
    """
    print(f"\n{'='*70}")
    print(f"TIER 1: SIGNAL RECALL EVALUATION")
    print(f"{'='*70}")

    positive = get_positive_drugs()
    results = []

    for drug_name, info in positive.items():
        cutoff = info["faers_cutoff"]
        print(f"\n  {drug_name} (cutoff: {cutoff})...", end=" ")

        signals = detect_signals(drug_name, date_end=cutoff, top_n=top_n,
                                verbose=False, enrich=False)
        flagged = [s for s in signals if s["flagged"]]
        matches, category = soc_match(flagged, drug_name)

        status = "HIT" if matches else "MISS"
        print(f"{status} ({len(flagged)} flagged, {len(matches)} SOC matches)")

        results.append({
            "drug": drug_name,
            "status": status,
            "category": category,
            "flagged_total": len(flagged),
            "soc_matches": len(matches),
            "top_match": matches[0] if matches else None,
            "total_reports": info.get("faers_cutoff", "all"),
        })

    hits = sum(1 for r in results if r["status"] == "HIT")
    total = len(results)

    print(f"\n  SIGNAL RECALL: {hits}/{total} ({100*hits/max(total,1):.0f}%)")
    return results, hits, total


def run_abstention_eval(top_n=30):
    """
    Tier 2: For each negative control drug, check for false positives.
    A good system flags 0 serious events on clean drugs.
    """
    print(f"\n{'='*70}")
    print(f"TIER 2: ABSTENTION ACCURACY EVALUATION")
    print(f"{'='*70}")

    negative = get_negative_controls()
    results = []

    for drug_name, info in negative.items():
        print(f"\n  {drug_name}...", end=" ")

        signals = detect_signals(drug_name, top_n=top_n, verbose=False, enrich=False)
        flagged = [s for s in signals if s["flagged"]]
        serious = [s for s in flagged if s.get("is_serious")]

        print(f"{len(flagged)} flagged, {len(serious)} serious")

        results.append({
            "drug": drug_name,
            "flagged_total": len(flagged),
            "serious_flagged": len(serious),
            "top_events": [s["event"] for s in flagged[:3]],
        })

    total_serious = sum(r["serious_flagged"] for r in results)
    perfect = total_serious == 0

    print(f"\n  SERIOUS FALSE POSITIVES: {total_serious}")
    if perfect:
        print(f"  PERFECT ABSTENTION on serious events")

    return results, total_serious


def run_full_evaluation():
    """Run all evaluation tiers and produce a summary report."""
    print(f"\n{'='*70}")
    print(f"PHARMASIGNAL — FULL EVALUATION")
    print(f"Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    # Tier 1
    recall_results, hits, total = run_signal_recall_eval()

    # Tier 2
    abstention_results, false_pos = run_abstention_eval()

    # Summary
    print(f"\n{'='*70}")
    print(f"EVALUATION SUMMARY")
    print(f"{'='*70}")

    print(f"\n  Ground truth: FDA Drug Safety Communications")
    print(f"  Matching: MedDRA System Organ Class root terms")
    print(f"  Methodology: Retrospective (pre-warning FAERS data only)")

    print(f"\n  TIER 1 — Signal Recall: {hits}/{total} ({100*hits/max(total,1):.0f}%)")
    for r in recall_results:
        marker = "✓" if r["status"] == "HIT" else "✗"
        match_info = ""
        if r["top_match"]:
            match_info = f" → {r['top_match']['event']} (PRR={r['top_match']['prr']})"
        print(f"    {marker} {r['drug']:<18} {r['category']:<28}{match_info}")

    print(f"\n  TIER 2 — Abstention Accuracy:")
    print(f"    Serious false positives: {false_pos}")
    for r in abstention_results:
        status = "CLEAN" if r["serious_flagged"] == 0 else f"{r['serious_flagged']} SERIOUS"
        print(f"    {r['drug']:<18} {r['flagged_total']} flagged, {status}")

    # Missed signal analysis
    missed = [r for r in recall_results if r["status"] == "MISS"]
    if missed:
        print(f"\n  MISSED SIGNAL ANALYSIS ({len(missed)} drugs):")
        for r in missed:
            print(f"    {r['drug']}: expected {r['category']}")
            print(f"      {r['flagged_total']} events flagged but none matched SOC keywords")

    # Save results
    eval_output = {
        "run_date": datetime.now().isoformat(),
        "signal_recall": {"hits": hits, "total": total, "pct": round(100*hits/max(total,1), 1)},
        "abstention": {"serious_false_positives": false_pos, "total_controls": len(abstention_results)},
        "recall_details": recall_results,
        "abstention_details": abstention_results,
    }

    output_path = Path("evaluation/eval_results.json")
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(eval_output, f, indent=2, default=str)
    print(f"\n  Results saved to: {output_path}")

    return eval_output


if __name__ == "__main__":
    run_full_evaluation()
