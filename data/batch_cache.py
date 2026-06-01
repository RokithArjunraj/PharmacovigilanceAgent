"""
Batch FAERS Data Cacher
========================
Pre-caches FAERS data for all 16 evaluation drugs.
Takes 20-30 minutes due to API rate limits. Run once.

Usage: python -m data.batch_cache
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.drug_names import DRUG_REGISTRY, get_positive_drugs, get_negative_controls
from signals.compute_signals import detect_signals


def cache_all_drugs():
    print("=" * 70)
    print("BATCH CACHING — All 16 evaluation drugs")
    print("This takes 20-30 minutes. Go get coffee.")
    print("=" * 70)

    positive = get_positive_drugs()
    negative = get_negative_controls()

    results = []

    # ── Positive cases: run with retrospective cutoff ──
    print(f"\n--- POSITIVE CASES ({len(positive)} drugs) ---\n")
    for drug_name, info in positive.items():
        cutoff = info["faers_cutoff"]
        print(f"\n>>> {drug_name} (cutoff: {cutoff})")
        try:
            signals = detect_signals(drug_name, date_end=cutoff, top_n=50, enrich=False)
            flagged = [s for s in signals if s["flagged"]]

            # Check if expected signals were detected
            expected = [e.lower() for e in info["expected_signals"]]
            detected = [
                s for s in flagged
                if any(exp in s["event"].lower() for exp in expected)
            ]

            status = "HIT" if detected else "MISS"
            results.append({
                "drug": drug_name,
                "type": "positive",
                "status": status,
                "flagged": len(flagged),
                "expected_found": len(detected),
                "top_3": [s["event"] for s in flagged[:3]],
            })

            print(f"  Flagged: {len(flagged)}, Expected found: {status}")
            if detected:
                for d in detected:
                    print(f"    HIT: {d['event']} (PRR={d['prr']})")

        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "drug": drug_name,
                "type": "positive",
                "status": "ERROR",
                "flagged": 0,
                "expected_found": 0,
                "top_3": [str(e)],
            })

    # ── Negative controls: run with all-time data ──
    print(f"\n--- NEGATIVE CONTROLS ({len(negative)} drugs) ---\n")
    for drug_name, info in negative.items():
        print(f"\n>>> {drug_name} (negative control)")
        try:
            signals = detect_signals(drug_name, top_n=30, enrich=False)
            flagged = [s for s in signals if s["flagged"]]

            results.append({
                "drug": drug_name,
                "type": "negative",
                "status": f"{len(flagged)} flagged",
                "flagged": len(flagged),
                "expected_found": 0,
                "top_3": [s["event"] for s in flagged[:3]],
            })

            print(f"  Flagged: {len(flagged)}")

        except Exception as e:
            print(f"  ERROR: {e}")

    # ── Summary ──
    print("\n")
    print("=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    print(f"\n{'Drug':<20} {'Type':<10} {'Status':<10} {'Flagged':>8} {'Top Signal':<30}")
    print("-" * 80)
    for r in results:
        top = r["top_3"][0] if r["top_3"] else "none"
        print(f"{r['drug']:<20} {r['type']:<10} {r['status']:<10} {r['flagged']:>8} {top[:30]:<30}")

    # Recall calculation
    positive_results = [r for r in results if r["type"] == "positive"]
    hits = sum(1 for r in positive_results if r["status"] == "HIT")
    total_pos = len(positive_results)
    errors = sum(1 for r in positive_results if r["status"] == "ERROR")

    print(f"\n{'='*70}")
    print(f"SIGNAL RECALL: {hits}/{total_pos} ({100*hits/max(total_pos,1):.0f}%)")
    if errors:
        print(f"ERRORS: {errors} drugs failed (check drug names)")
    print(f"{'='*70}")

    # Missed signals
    missed = [r for r in positive_results if r["status"] == "MISS"]
    if missed:
        print(f"\nMISSED SIGNALS (investigate these):")
        for r in missed:
            print(f"  {r['drug']}: top flagged = {r['top_3']}")

    # Negative control summary
    neg_results = [r for r in results if r["type"] == "negative"]
    print(f"\nNEGATIVE CONTROLS:")
    for r in neg_results:
        print(f"  {r['drug']}: {r['flagged']} events flagged")

    print("\nAll data cached. Subsequent runs will be instant.")
    print("Next: Person B runs check_label_gap on flagged signals to classify novel vs known.")


if __name__ == "__main__":
    cache_all_drugs()