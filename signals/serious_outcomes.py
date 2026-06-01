"""
signals/serious_outcomes.py
---------------------------
Shared list imported by both Person A (compute_signals.py)
and Person B (check_label_gap.py).

Single source of truth — never duplicate this list.
"""

SERIOUS_OUTCOMES = [
    "myocardial infarction", "cardiac arrest", "sudden cardiac death",
    "liver failure", "hepatic failure", "acute liver failure",
    "anaphylaxis", "anaphylactic shock",
    "stroke", "cerebrovascular accident",
    "suicidal ideation", "completed suicide",
    "aplastic anaemia", "agranulocytosis",
    "stevens-johnson syndrome", "toxic epidermal necrolysis",
    "pulmonary embolism", "rhabdomyolysis", "renal failure acute",
    "birth defect", "congenital anomaly",
    "blindness", "deafness", "paralysis",
]

RARE_DRUG_THRESHOLD    = 1000   # total reports below this = rare drug
SERIOUS_PRR_THRESHOLD  = 1.5    # lower bar for serious events
STANDARD_PRR_THRESHOLD = 2.0
SERIOUS_MIN_COUNT      = 2
STANDARD_MIN_COUNT     = 3