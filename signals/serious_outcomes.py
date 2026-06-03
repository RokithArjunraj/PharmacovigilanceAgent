"""
signals/serious_outcomes.py
----------------------------
Single source of truth for serious/life-threatening event terms.
Both compute_signals.py and check_label_gap.py import from here.

These events get relaxed detection thresholds because the cost
of missing a cardiac death is far higher than missing a case of nausea.
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
