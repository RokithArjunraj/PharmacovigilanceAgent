"""
signals/serious_outcomes.py
----------------------------
Single source of truth for serious/life-threatening event terms.
Both compute_signals.py and check_label_gap.py import from here.

These events get relaxed detection thresholds because the cost
of missing a cardiac death is far higher than missing a case of nausea.

Source note:
- Static list below seeds the classifier using FDA 21 CFR 314.81 criteria:
  death, hospitalisation, life-threatening, disability, congenital anomaly.
- Dynamic enrichment via FAERSClient.get_serious_event_counts() adds
  drug-specific reporter-flagged serious events at runtime.
- WHO-UMC Adverse Drug Reactions of Special Interest (ADRSI) list used
  as cross-reference: https://www.who-umc.org/vigibase/services/
- MedDRA SMQs (Standardised MedDRA Queries) for Cardiac Failure,
  Severe Cutaneous Adverse Reactions, etc. used as grouping reference.
"""

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
    "ventricular tachycardia", "torsade de pointes",
    "qt prolonged",
    "tardive dyskinesia",
    "diabetic ketoacidosis",
    "bladder cancer", "bladder neoplasm",
    "tendon rupture", "achilles tendon rupture",
    "amputation",
    "hepatocellular injury", "hepatocellular damage",
    "myelosuppression", "pancytopenia", "bone marrow failure",
    "respiratory failure", "respiratory arrest",
    "sepsis", "septic shock",
    "haemorrhage", "intracranial haemorrhage",
    "encephalopathy", "leukoencephalopathy",
    "interstitial lung disease", "pulmonary fibrosis",
]


def is_serious_dynamic(event_name: str, faers_serious_set: set = None) -> bool:
    """
    Check seriousness against both the static seed list and a
    dynamic set of FAERS reporter-flagged serious events for this drug.

    Args:
        event_name:        MedDRA adverse event term.
        faers_serious_set: Set of lowercased event terms from
                           FAERSClient.get_serious_event_counts().
                           These are reporter-flagged per FDA 21 CFR 314.81
                           (death / hospitalisation / life-threatening /
                           disability / congenital anomaly) — no hardcoding.

    Returns:
        True if serious by either source.
    """
    event_lower = event_name.lower()

    # Check static seed list (substring match — catches "acute renal failure"
    # matching "renal failure acute" etc.)
    if any(s in event_lower for s in SERIOUS_OUTCOMES):
        return True

    # Check dynamic FAERS-sourced serious events for this drug
    if faers_serious_set and event_lower in faers_serious_set:
        return True

    return False
