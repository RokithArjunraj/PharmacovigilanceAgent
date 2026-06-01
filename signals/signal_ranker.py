"""
Signal Ranker
==============
Formats and filters signal detection output.
Thin utility layer on top of compute_signals.py.
"""

import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signals.compute_signals import detect_signals, signals_to_dataframe


def get_signal_report(drug_name, date_end=None, top_n=50):
    """
    Generate a complete signal report for a drug.
    Returns a dict with summary stats and the full signal table.
    """
    signals = detect_signals(drug_name, date_end=date_end, top_n=top_n)
    flagged = [s for s in signals if s["flagged"]]
    serious_flagged = [s for s in flagged if s.get("is_serious")]

    return {
        "drug": drug_name,
        "date_end": date_end,
        "total_events_analysed": len(signals),
        "total_flagged": len(flagged),
        "serious_flagged": len(serious_flagged),
        "signals": signals,
        "flagged_signals": flagged,
        "top_signal": flagged[0] if flagged else None,
        "has_confounding_concerns": any(
            s.get("confounding_warning") for s in flagged
        ),
        "has_sex_alerts": any(
            s.get("sex_breakdown", {}).get("sex_alert") for s in flagged
        ),
    }


def print_signal_report(report):
    """Pretty-print a signal report to console."""
    print(f"\n{'='*70}")
    print(f"SIGNAL REPORT: {report['drug']}")
    if report["date_end"]:
        print(f"Mode: Retrospective (data up to {report['date_end']})")
    print(f"{'='*70}")
    print(f"Events analysed: {report['total_events_analysed']}")
    print(f"Signals flagged: {report['total_flagged']} "
          f"({report['serious_flagged']} serious)")

    if report["has_confounding_concerns"]:
        print(f"[!] Confounding concerns detected — see details below")
    if report["has_sex_alerts"]:
        print(f"[!] Sex-stratified imbalance detected — see details below")

    flagged = report["flagged_signals"]
    if not flagged:
        print("\nNo signals flagged.")
        return

    print(f"\n{'Event':<30} {'Score':>6} {'PRR':>7} {'N':>5} {'Serious':>8} {'Threshold':>10}")
    print("-" * 70)
    for s in flagged:
        ser = "YES" if s["is_serious"] else ""
        print(f"{s['event'][:30]:<30} {s['composite_score']:>6.2f} "
              f"{s['prr']:>7.2f} {s['count']:>5} {ser:>8} {s['threshold_used']:>10}")

    # Details for top 5
    print(f"\n--- DETAILS (top {min(5, len(flagged))}) ---")
    for s in flagged[:5]:
        print(f"\n  {s['event']}:")
        print(f"    PRR={s['prr']} (CI: {s['prr_ci_lower']}-{s['prr_ci_upper']}), "
              f"ROR={s['ror']}, chi2={s['chi_squared']}")
        if s.get("confounding_warning"):
            print(f"    CONFOUNDING: {s['confounding_warning']}")
        sex = s.get("sex_breakdown", {})
        if sex.get("sex_alert"):
            print(f"    SEX ALERT: {sex['sex_alert']}")
        elif sex.get("male") or sex.get("female"):
            print(f"    Sex: M={sex.get('male', 0)}, F={sex.get('female', 0)}")


if __name__ == "__main__":
    report = get_signal_report("rosiglitazone", top_n=25)
    print_signal_report(report)

    print("\n\n")
    report_retro = get_signal_report("rosiglitazone", date_end="20070101", top_n=50)
    print_signal_report(report_retro)
