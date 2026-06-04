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


import re

def is_serious_dynamic(event_name: str, faers_serious_set: set = None) -> bool:
    event_lower = event_name.lower()
    if any(re.search(r'\b' + re.escape(s) + r'\b', event_lower) for s in SERIOUS_OUTCOMES):
        return True
    if faers_serious_set and event_lower in faers_serious_set:
        return True
    return False
