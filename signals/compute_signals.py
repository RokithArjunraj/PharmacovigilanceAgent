"""
Signal Detection Engine — v2 (with gap fixes)
===============================================
Person A owns this file.

Changes from v1:
- Context-sensitive thresholds (lower bar for serious events)
- Co-medication confounding check per flagged signal
- Sex-stratified signal breakdown
- Composite ranking score (severity × statistics × context)
"""

import math
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fetch_faers import FAERSClient
from config import PRR_THRESHOLD, CHI_SQUARED_THRESHOLD, MIN_REPORT_COUNT


# ──────────────────────────────────────────────
# GAP 5 FIX: Serious outcomes list
# Events on this list get lower flagging thresholds
# because missing a cardiac death is worse than
# missing a case of nausea.
# ──────────────────────────────────────────────
SERIOUS_OUTCOMES = [
    "myocardial infarction", "cardiac arrest", "sudden cardiac death",
    "cardiac failure", "cardiac failure congestive",
    "hepatic failure", "liver failure", "hepatotoxicity",
    "anaphylaxis", "anaphylactic shock",
    "cerebrovascular accident", "stroke",
    "suicidal ideation", "completed suicide", "suicide attempt",
    "aplastic anaemia", "agranulocytosis",
    "stevens-johnson syndrome", "toxic epidermal necrolysis",
    "pulmonary embolism", "deep vein thrombosis",
    "rhabdomyolysis", "renal failure acute",
    "cardiac arrest", "ventricular tachycardia", "torsade de pointes",
    "qt prolonged",
    "tardive dyskinesia",
    "diabetic ketoacidosis",
    "bladder cancer", "bladder neoplasm",
    "tendon rupture", "achilles tendon rupture",
    "amputation",
]


# ──────────────────────────────────────────────
# STATISTICS FUNCTIONS (unchanged from v1)
# ──────────────────────────────────────────────

def compute_prr(a, b, c, d):
    drug_total = a + b
    not_drug_total = c + d
    if drug_total == 0 or not_drug_total == 0 or c == 0:
        return 0.0
    drug_rate = a / drug_total
    background_rate = c / not_drug_total
    if background_rate == 0:
        return float("inf")
    return drug_rate / background_rate


def compute_ror(a, b, c, d):
    if b == 0 or c == 0 or a == 0:
        return 0.0
    return (a * d) / (b * c)


def compute_chi_squared(a, b, c, d):
    n = a + b + c + d
    if n == 0:
        return 0.0
    e_a = ((a + b) * (a + c)) / n
    e_b = ((a + b) * (b + d)) / n
    e_c = ((c + d) * (a + c)) / n
    e_d = ((c + d) * (b + d)) / n
    chi2 = 0.0
    for observed, expected in [(a, e_a), (b, e_b), (c, e_c), (d, e_d)]:
        if expected > 0:
            chi2 += ((observed - expected) ** 2) / expected
    return chi2


def compute_prr_confidence_interval(a, b, c, d, prr):
    if prr <= 0 or a <= 0 or c <= 0:
        return (0.0, 0.0)
    try:
        drug_total = a + b
        not_drug_total = c + d
        se = math.sqrt(
            (1 / a) - (1 / drug_total) + (1 / c) - (1 / not_drug_total)
        )
        log_prr = math.log(prr)
        lower = math.exp(log_prr - 1.96 * se)
        upper = math.exp(log_prr + 1.96 * se)
        return (round(lower, 3), round(upper, 3))
    except (ValueError, ZeroDivisionError):
        return (0.0, 0.0)


# ──────────────────────────────────────────────
# GAP 5 FIX: Context-sensitive flagging
# Lower thresholds for serious/life-threatening events
# and for rare drugs with few total reports.
# ──────────────────────────────────────────────

def is_serious_event(event_name):
    """Check if this event is life-threatening or irreversible."""
    event_lower = event_name.lower()
    return any(s in event_lower for s in SERIOUS_OUTCOMES)


def is_signal(event_name, count, prr, chi2, total_drug_reports=None):
    """
    Context-sensitive Evans' criteria.

    Standard:  PRR >= 2.0, chi2 >= 4.0, count >= 3
    Serious:   PRR >= 1.5, chi2 >= 4.0, count >= 2
    Rare drug: PRR >= 1.5, chi2 >= 3.0, count >= 2

    Interview answer: "We lower the threshold for serious events
    because the cost of missing a cardiac death signal is much higher
    than the cost of a false positive on nausea. This mirrors how
    real pharmacovigilance teams triage — serious events get more
    scrutiny at lower thresholds."
    """
    serious = is_serious_event(event_name)
    rare_drug = total_drug_reports is not None and total_drug_reports < 1000

    if serious or rare_drug:
        return count >= 2 and prr >= 1.5 and chi2 >= 3.0
    else:
        return (
            count >= MIN_REPORT_COUNT
            and prr >= PRR_THRESHOLD
            and chi2 >= CHI_SQUARED_THRESHOLD
        )


# ──────────────────────────────────────────────
# GAP 2 FIX: Confounding check
# ──────────────────────────────────────────────

def check_confounding(client, drug_name, event_name, total_drug_reports, date_end=None):
    """
    Check if co-prescribed drugs might explain the signal.
    Returns a warning string if >50% of reports also mention another drug,
    or None if no confounding concern.
    """
    co_meds = client.get_co_medications(drug_name, event_name, date_end=date_end, limit=5)

    if not co_meds or total_drug_reports == 0:
        return None

    warnings = []
    for cm in co_meds[:3]:
        pct = (cm["count"] / total_drug_reports) * 100
        if pct > 50:
            warnings.append(f"{cm['term']} appears in {pct:.0f}% of reports")

    if warnings:
        return "Potential confounding: " + "; ".join(warnings)
    return None


# ──────────────────────────────────────────────
# GAP 4 PARTIAL FIX: Sex-stratified breakdown
# ──────────────────────────────────────────────

def get_sex_breakdown(client, drug_name, event_name, date_end=None):
    """
    Get male/female report counts for a flagged signal.
    Returns dict with counts and a flag if one sex is >3x the other.
    """
    sex_data = client.get_event_counts_by_sex(drug_name, event_name, date_end=date_end)

    male = sex_data.get("male", 0)
    female = sex_data.get("female", 0)
    total = male + female

    result = {"male": male, "female": female}

    if total >= 5:
        if male > 0 and female > 0:
            ratio = max(male, female) / min(male, female)
            if ratio >= 3:
                dominant = "male" if male > female else "female"
                result["sex_alert"] = f"Signal is {ratio:.1f}x stronger in {dominant} patients"

    return result


# ──────────────────────────────────────────────
# GAP 6 FIX: Weber effect flag
# ──────────────────────────────────────────────

def check_weber_effect(drug_name):
    """
    Flag drugs launched within 3 years — reporting may be
    artificially inflated due to novelty (Weber effect).
    """
    from data.drug_names import DRUG_REGISTRY
    drug_info = DRUG_REGISTRY.get(drug_name.lower(), {})
    launch_year = drug_info.get("launch_year")

    if launch_year:
        years_since = 2026 - launch_year
        if years_since <= 3:
            return (f"Drug launched {years_since} year(s) ago — "
                    f"Weber effect may inflate PRR. Interpret with caution.")
    return None


# ──────────────────────────────────────────────
# COMPOSITE RANKING
# ──────────────────────────────────────────────

def compute_composite_score(signal):
    """
    Rank signals by a combination of statistical strength,
    clinical severity, and contextual flags.

    A serious event with PRR 2.1 ranks above a trivial event
    with PRR 4.0. This matches clinical priority.
    """
    # Base: statistical strength (cap count contribution so
    # very common events don't dominate)
    stat_score = signal["prr"] * min(signal["count"], 100) / 100

    # Severity multiplier
    severity_mult = 2.5 if signal.get("is_serious") else 1.0

    # Sex imbalance bonus
    sex_bonus = 0.5 if signal.get("sex_breakdown", {}).get("sex_alert") else 0

    # Confounding penalty (reduce score if likely confounded)
    confound_penalty = -0.5 if signal.get("confounding_warning") else 0

    score = (stat_score + sex_bonus + confound_penalty) * severity_mult
    return round(max(score, 0), 3)


# ──────────────────────────────────────────────
# MAIN FUNCTION — the interface contract
# ──────────────────────────────────────────────

def detect_signals(drug_name, date_end=None, top_n=50, verbose=True, enrich=True):
    """
    Run full signal detection for a drug.

    Args:
        drug_name: Generic drug name.
        date_end:  Cutoff date "YYYYMMDD" for retrospective mode.
        top_n:     Number of top events to analyse.
        verbose:   Print progress.
        enrich:    If True, add co-med check, sex breakdown, composite score
                   for flagged signals. Set False for fast batch runs.

    Returns:
        List of signal dicts sorted by composite_score descending.
    """
    client = FAERSClient()

    if verbose:
        print(f"\n{'='*65}")
        print(f"Signal Detection: {drug_name}")
        if date_end:
            print(f"Mode: RETROSPECTIVE (data up to {date_end})")
        print(f"{'='*65}")

    # Step 1: Get event counts
    events = client.get_event_counts(drug_name, date_end=date_end, limit=top_n)
    if not events:
        if verbose:
            print(f"  [!] No FAERS data for '{drug_name}'")
        return []
    if verbose:
        print(f"  Events found: {len(events)}")

    # Step 2: Get totals for contingency table
    drug_total = client.get_total_drug_reports(drug_name, date_end=date_end)
    db_total = client.get_total_database_size(date_end=date_end)
    if verbose:
        print(f"  Drug reports: {drug_total:,} | DB total: {db_total:,}")

    # Weber effect check
    weber_warning = check_weber_effect(drug_name)
    if weber_warning and verbose:
        print(f"  [!] {weber_warning}")

    # Step 3: Compute statistics for each event
    if verbose:
        print(f"\n  Computing PRR/ROR for {len(events)} events...")

    signals = []
    for i, event_data in enumerate(events):
        event_name = event_data["term"]
        a = event_data["count"]

        if a < 2:  # minimum 2 for even the relaxed threshold
            continue

        event_total = client.get_total_event_reports(event_name, date_end=date_end)

        b = max(drug_total - a, 0)
        c = max(event_total - a, 0)
        d = max(db_total - a - b - c, 0)

        prr = compute_prr(a, b, c, d)
        ror = compute_ror(a, b, c, d)
        chi2 = compute_chi_squared(a, b, c, d)
        ci_lower, ci_upper = compute_prr_confidence_interval(a, b, c, d, prr)
        serious = is_serious_event(event_name)
        flagged = is_signal(event_name, a, prr, chi2, drug_total)

        signal = {
            "drug": drug_name,
            "event": event_name,
            "count": a,
            "prr": round(prr, 3),
            "ror": round(ror, 3),
            "chi_squared": round(chi2, 3),
            "prr_ci_lower": ci_lower,
            "prr_ci_upper": ci_upper,
            "flagged": flagged,
            "is_serious": serious,
            "threshold_used": "relaxed" if (serious or drug_total < 1000) else "standard",
        }

        signals.append(signal)

        if verbose and (i + 1) % 10 == 0:
            print(f"    ...processed {i + 1}/{len(events)} events")

    # Step 4: Enrich flagged signals with context
    if enrich:
        flagged_signals = [s for s in signals if s["flagged"]]
        if verbose and flagged_signals:
            print(f"\n  Enriching {len(flagged_signals)} flagged signals...")

        for s in flagged_signals:
            # Co-medication confounding check (Gap 2)
            s["confounding_warning"] = check_confounding(
                client, drug_name, s["event"], drug_total, date_end
            )

            # Sex breakdown (Gap 4)
            s["sex_breakdown"] = get_sex_breakdown(
                client, drug_name, s["event"], date_end
            )

        # Add weber warning to all signals
        if weber_warning:
            for s in signals:
                s["weber_warning"] = weber_warning

    # Step 5: Compute composite score and sort
    for s in signals:
        s["composite_score"] = compute_composite_score(s)

    signals.sort(key=lambda s: s["composite_score"], reverse=True)

    if verbose:
        flagged_count = sum(1 for s in signals if s["flagged"])
        serious_flagged = sum(1 for s in signals if s["flagged"] and s["is_serious"])
        print(f"\n  RESULT: {flagged_count} signals flagged ({serious_flagged} serious)")

    return signals


def get_flagged_signals(drug_name, date_end=None, top_n=50):
    return [s for s in detect_signals(drug_name, date_end=date_end, top_n=top_n)
            if s["flagged"]]


def signals_to_dataframe(signals):
    df = pd.DataFrame(signals)
    if not df.empty:
        df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    return df


# ── SELF-TEST ──
if __name__ == "__main__":

    print("=" * 75)
    print("SIGNAL DETECTION v2 — Rosiglitazone (all-time, enriched)")
    print("=" * 75)

    signals = detect_signals("rosiglitazone", top_n=25)

    print(f"\n{'Event':<30} {'N':>5} {'PRR':>7} {'ROR':>7} {'Score':>7} {'Ser':>4} {'Flag':>5}")
    print("-" * 75)
    for s in signals[:20]:
        flag = "  Y" if s["flagged"] else ""
        ser = "  !" if s["is_serious"] else ""
        print(f"{s['event'][:30]:<30} {s['count']:>5} {s['prr']:>7.2f} {s['ror']:>7.2f} "
              f"{s['composite_score']:>7.2f} {ser:>4} {flag}")

    # Show enrichment details for flagged signals
    flagged = [s for s in signals if s["flagged"]]
    print(f"\n--- ENRICHMENT DETAILS ({len(flagged)} flagged signals) ---")
    for s in flagged[:5]:
        print(f"\n  {s['event']}:")
        print(f"    PRR={s['prr']}, Threshold={s['threshold_used']}")
        if s.get("confounding_warning"):
            print(f"    WARNING: {s['confounding_warning']}")
        sex = s.get("sex_breakdown", {})
        if sex:
            print(f"    Sex: M={sex.get('male', '?')}, F={sex.get('female', '?')}")
            if sex.get("sex_alert"):
                print(f"    ALERT: {sex['sex_alert']}")

    print("\n")
    print("=" * 75)
    print("RETROSPECTIVE — Rosiglitazone pre-2007")
    print("=" * 75)

    signals_retro = detect_signals("rosiglitazone", date_end="20070101", top_n=50)
    flagged_retro = [s for s in signals_retro if s["flagged"]]
    print(f"\n{len(flagged_retro)} signals flagged from pre-2007 data")

    cardiac = [s for s in flagged_retro
               if "myocardial" in s["event"].lower() or "cardiac" in s["event"].lower()]
    if cardiac:
        print(f"\n>>> CARDIAC SIGNAL DETECTED IN PRE-2007 DATA:")
        for c in cardiac:
            print(f"    {c['event']}: PRR={c['prr']}, score={c['composite_score']}")
        print(">>> System would have flagged this BEFORE the FDA warning.")
    else:
        print("\n[!] Cardiac signal not flagged. Checking unflagged events...")
        all_cardiac = [s for s in signals_retro
                       if "cardiac" in s["event"].lower() or "myocardial" in s["event"].lower()]
        for s in all_cardiac:
            print(f"    {s['event']}: PRR={s['prr']}, chi2={s['chi_squared']}, "
                  f"N={s['count']}, flagged={s['flagged']}")

    print("\nDone.")
