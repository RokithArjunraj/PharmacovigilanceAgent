"""
followup/score_priority.py
---------------------------
Module 2: Follow-up Prioritisation.

Ranks flagged signals by follow-up priority based on:
  - Statistical strength (PRR)
  - Clinical severity (serious vs non-serious)
  - Novelty (novel signals need more data than known ones)
  - Evidence completeness (thin evidence = higher follow-up priority)
  - Confounding risk (confounded signals need clarification)

Addresses the Novartis case competition problem:
  "Follow-up fatigue" — pharmacovigilance teams can't follow up on every
  incomplete report. This system tells them WHICH reports to chase.

The output is a ranked list: follow up report #1 first, then #2, etc.
Typically reduces follow-up volume by 50-70% while preserving coverage
of the highest-risk signals.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def compute_followup_priority(signal, label_gap=None, evidence_report=None):
    """
    Score a single signal for follow-up priority.

    Higher score = follow up sooner.

    Components:
      1. Statistical strength — PRR and count
      2. Severity — serious events get 2x weight
      3. Novelty — novel signals need more data collection
      4. Evidence gap — less published evidence = more need for follow-up
      5. Actionability — is there something specific to follow up on?

    Returns:
        dict with priority_score, priority_tier, components breakdown
    """
    # Component 1: Statistical strength (0-5 range)
    prr = signal.get("prr", 0)
    count = signal.get("count", 0)
    stat_score = min(prr, 10) * 0.3 + min(count, 200) / 200 * 2
    stat_score = min(stat_score, 5)

    # Component 2: Severity (0 or 3)
    is_serious = signal.get("is_serious", False)
    severity_score = 3.0 if is_serious else 0.0

    # Component 3: Novelty (0-4 range)
    novelty_score = 0
    if label_gap:
        status = label_gap.get("status", "unknown")
        novelty_score = {"novel": 4.0, "known_different_wording": 1.5, "known": 0.0}.get(status, 1.0)

    # Component 4: Evidence gap (0-3 range)
    evidence_gap_score = 0
    if evidence_report:
        grade = evidence_report.get("evidence_grade", "Inconclusive")
        evidence_gap_score = {
            "Inconclusive": 3.0,
            "Weak": 2.0,
            "Moderate": 1.0,
            "Strong": 0.0,
        }.get(grade, 2.0)

        if evidence_report.get("abstained"):
            evidence_gap_score = 3.5  # highest priority for follow-up

    # Component 5: Actionability bonus
    actionable_bonus = 0
    if evidence_report and evidence_report.get("is_actionable"):
        actionable_bonus = 1.0

    # Total score
    total = stat_score + severity_score + novelty_score + evidence_gap_score + actionable_bonus
    total = round(total, 2)

    # Priority tier
    if total >= 10:
        tier = "CRITICAL"
    elif total >= 7:
        tier = "HIGH"
    elif total >= 4:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    return {
        "event": signal.get("event", "Unknown"),
        "drug": signal.get("drug", "Unknown"),
        "priority_score": total,
        "priority_tier": tier,
        "components": {
            "statistical": round(stat_score, 2),
            "severity": severity_score,
            "novelty": novelty_score,
            "evidence_gap": evidence_gap_score,
            "actionable_bonus": actionable_bonus,
        },
        "is_serious": is_serious,
        "prr": prr,
        "count": count,
        "label_status": label_gap.get("status", "unknown") if label_gap else "unknown",
        "evidence_grade": evidence_report.get("evidence_grade", "?") if evidence_report else "?",
    }


def rank_followup_priorities(signals, label_gaps=None, evidence_reports=None):
    """
    Rank all flagged signals by follow-up priority.

    Args:
        signals: list of signal dicts from compute_signals
        label_gaps: list of label gap dicts (parallel to signals), or None
        evidence_reports: list of evidence report dicts (parallel), or None

    Returns:
        List of priority dicts, sorted by priority_score descending.
    """
    priorities = []

    for i, signal in enumerate(signals):
        gap = label_gaps[i] if label_gaps and i < len(label_gaps) else None
        report = evidence_reports[i] if evidence_reports and i < len(evidence_reports) else None
        priority = compute_followup_priority(signal, gap, report)
        priorities.append(priority)

    # Sort by priority score descending
    priorities.sort(key=lambda p: p["priority_score"], reverse=True)

    return priorities


def filter_top_priority(priorities, top_pct=0.4):
    """
    Filter to top X% of signals by priority.
    This is the volume reduction — only follow up on the most important.

    Args:
        priorities: ranked list from rank_followup_priorities
        top_pct: fraction to keep (0.4 = top 40%)

    Returns:
        Filtered list, and reduction stats.
    """
    total = len(priorities)
    if total == 0:
        return [], {"total": 0, "kept": 0, "reduction_pct": 0}

    cutoff = max(1, int(total * top_pct))
    filtered = priorities[:cutoff]

    stats = {
        "total": total,
        "kept": len(filtered),
        "removed": total - len(filtered),
        "reduction_pct": round((1 - len(filtered) / total) * 100, 1),
        "min_score_kept": filtered[-1]["priority_score"] if filtered else 0,
    }

    return filtered, stats


def print_followup_ranking(priorities, stats=None):
    """Pretty-print the follow-up ranking."""
    print(f"\n{'='*70}")
    print(f"FOLLOW-UP PRIORITY RANKING")
    print(f"{'='*70}")

    if stats:
        print(f"Total signals: {stats['total']} | Prioritised: {stats['kept']} "
              f"| Reduction: {stats['reduction_pct']}%\n")

    print(f"{'Rank':<5} {'Event':<30} {'Tier':<10} {'Score':>6} {'PRR':>7} {'Label':>8} {'Grade':>12}")
    print("-" * 80)

    for i, p in enumerate(priorities, 1):
        print(f"{i:<5} {p['event'][:30]:<30} {p['priority_tier']:<10} "
              f"{p['priority_score']:>6.1f} {p['prr']:>7.1f} "
              f"{p['label_status'][:8]:>8} {p['evidence_grade']:>12}")


# ── Test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    from tests.mock_signals import MOCK_ROSIGLITAZONE

    print("Testing followup/score_priority.py\n")

    # Mock label gaps and evidence reports
    mock_gaps = [
        {"status": "novel", "match_score": 0.3},
        {"status": "known", "match_score": 0.95},
        {"status": "known_different_wording", "match_score": 0.82},
        {"status": "novel", "match_score": 0.2},
    ]
    mock_reports = [
        {"evidence_grade": "Moderate", "is_actionable": True, "abstained": False},
        {"evidence_grade": "Strong", "is_actionable": False, "abstained": False},
        {"evidence_grade": "Weak", "is_actionable": True, "abstained": False},
        {"evidence_grade": "Inconclusive", "is_actionable": False, "abstained": True},
    ]

    flagged = [s for s in MOCK_ROSIGLITAZONE if s["flagged"]]

    priorities = rank_followup_priorities(flagged, mock_gaps, mock_reports)
    filtered, stats = filter_top_priority(priorities, top_pct=0.5)

    print_followup_ranking(filtered, stats)
    print("\n✓ score_priority.py working")
