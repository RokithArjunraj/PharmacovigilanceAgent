"""
Drug Name Registry
===================
SHARED FILE — both Person A and Person B import from this.

Maps each evaluation drug to its search terms for each API.
Start with these entries. Add more as you validate them.

HOW TO VALIDATE A NEW DRUG:
1. Test in browser: https://api.fda.gov/drug/event.json?search=patient.drug.medicinalproduct:"DRUG_NAME"&limit=1
2. If zero results, try with salt form (hydrochloride, maleate, etc.)
3. Add the working term to faers_terms below.
"""


DRUG_REGISTRY = {
    # ── POSITIVE CASES (known safety signals) ──

    "rosiglitazone": {
        "faers_terms": ["rosiglitazone", "rosiglitazone maleate"],
        "dailymed_term": "rosiglitazone",
        "pubmed_term": "rosiglitazone",
        "brand": "Avandia",
        "expected_signals": ["Myocardial infarction", "Cardiovascular disorder"],
        "fda_warning_date": "2007-05-21",
        "faers_cutoff": "20070101",
    },

    "pioglitazone": {
        "faers_terms": ["pioglitazone", "pioglitazone hydrochloride"],
        "dailymed_term": "pioglitazone",
        "pubmed_term": "pioglitazone",
        "brand": "Actos",
        "expected_signals": ["Bladder cancer", "Bladder neoplasm"],
        "fda_warning_date": "2011-06-15",
        "faers_cutoff": "20110101",
    },

    "ciprofloxacin": {
        "faers_terms": ["ciprofloxacin", "ciprofloxacin hydrochloride"],
        "dailymed_term": "ciprofloxacin",
        "pubmed_term": "ciprofloxacin",
        "brand": "Cipro",
        "expected_signals": ["Tendon rupture", "Tendon disorder", "Achilles tendon rupture"],
        "fda_warning_date": "2008-07-08",
        "faers_cutoff": "20080101",
    },

    "canagliflozin": {
        "faers_terms": ["canagliflozin"],
        "dailymed_term": "canagliflozin",
        "pubmed_term": "canagliflozin",
        "brand": "Invokana",
        "expected_signals": ["Amputation", "Toe amputation", "Limb amputation"],
        "fda_warning_date": "2017-05-16",
        "faers_cutoff": "20170101",
    },

    "zolpidem": {
        "faers_terms": ["zolpidem", "zolpidem tartrate"],
        "dailymed_term": "zolpidem",
        "pubmed_term": "zolpidem",
        "brand": "Ambien",
        "expected_signals": ["Somnolence", "Road traffic accident", "Impaired driving"],
        "fda_warning_date": "2013-01-10",
        "faers_cutoff": "20120701",
    },

    "loperamide": {
        "faers_terms": ["loperamide", "loperamide hydrochloride"],
        "dailymed_term": "loperamide",
        "pubmed_term": "loperamide",
        "brand": "Imodium",
        "expected_signals": ["Cardiac arrest", "QT prolonged", "Ventricular tachycardia"],
        "fda_warning_date": "2016-06-07",
        "faers_cutoff": "20160101",
    },

    "omeprazole": {
        "faers_terms": ["omeprazole"],
        "dailymed_term": "omeprazole",
        "pubmed_term": "omeprazole",
        "brand": "Prilosec",
        "expected_signals": ["Hypomagnesaemia", "Clostridium difficile colitis"],
        "fda_warning_date": "2012-03-02",
        "faers_cutoff": "20110601",
    },

    "varenicline": {
        "faers_terms": ["varenicline", "varenicline tartrate"],
        "dailymed_term": "varenicline",
        "pubmed_term": "varenicline",
        "brand": "Chantix",
        "expected_signals": ["Suicidal ideation", "Depression", "Abnormal behaviour"],
        "fda_warning_date": "2009-07-01",
        "faers_cutoff": "20090101",
    },

    "dapagliflozin": {
        "faers_terms": ["dapagliflozin"],
        "dailymed_term": "dapagliflozin",
        "pubmed_term": "dapagliflozin",
        "brand": "Farxiga",
        "expected_signals": ["Diabetic ketoacidosis", "Ketoacidosis"],
        "fda_warning_date": "2015-05-15",
        "faers_cutoff": "20150101",
    },

    "metoclopramide": {
        "faers_terms": ["metoclopramide", "metoclopramide hydrochloride"],
        "dailymed_term": "metoclopramide",
        "pubmed_term": "metoclopramide",
        "brand": "Reglan",
        "expected_signals": ["Tardive dyskinesia", "Dyskinesia"],
        "fda_warning_date": "2009-02-26",
        "faers_cutoff": "20080601",
    },

    "dronedarone": {
        "faers_terms": ["dronedarone", "dronedarone hydrochloride"],
        "dailymed_term": "dronedarone",
        "pubmed_term": "dronedarone",
        "brand": "Multaq",
        "expected_signals": ["Hepatotoxicity", "Hepatic failure", "Liver injury"],
        "fda_warning_date": "2011-01-14",
        "faers_cutoff": "20101001",
    },

    "olmesartan": {
        "faers_terms": ["olmesartan", "olmesartan medoxomil"],
        "dailymed_term": "olmesartan",
        "pubmed_term": "olmesartan",
        "brand": "Benicar",
        "expected_signals": ["Sprue-like enteropathy", "Diarrhoea", "Villous atrophy"],
        "fda_warning_date": "2013-07-03",
        "faers_cutoff": "20130101",
    },

    # ── NEGATIVE CONTROLS ──

    "lisinopril": {
        "faers_terms": ["lisinopril"],
        "dailymed_term": "lisinopril",
        "pubmed_term": "lisinopril",
        "brand": "Zestril",
        "expected_signals": [],
        "fda_warning_date": None,
        "faers_cutoff": None,
        "is_negative_control": True,
    },

    "levothyroxine": {
        "faers_terms": ["levothyroxine", "levothyroxine sodium"],
        "dailymed_term": "levothyroxine",
        "pubmed_term": "levothyroxine",
        "brand": "Synthroid",
        "expected_signals": [],
        "fda_warning_date": None,
        "faers_cutoff": None,
        "is_negative_control": True,
    },

    "amlodipine": {
        "faers_terms": ["amlodipine", "amlodipine besylate"],
        "dailymed_term": "amlodipine",
        "pubmed_term": "amlodipine",
        "brand": "Norvasc",
        "expected_signals": [],
        "fda_warning_date": None,
        "faers_cutoff": None,
        "is_negative_control": True,
    },

    "cetirizine": {
        "faers_terms": ["cetirizine", "cetirizine hydrochloride"],
        "dailymed_term": "cetirizine",
        "pubmed_term": "cetirizine",
        "brand": "Zyrtec",
        "expected_signals": [],
        "fda_warning_date": None,
        "faers_cutoff": None,
        "is_negative_control": True,
    },
}


def get_positive_drugs():
    """Return only drugs with known safety signals."""
    return {
        name: info for name, info in DRUG_REGISTRY.items()
        if info.get("expected_signals") and not info.get("is_negative_control")
    }


def get_negative_controls():
    """Return only negative control drugs."""
    return {
        name: info for name, info in DRUG_REGISTRY.items()
        if info.get("is_negative_control")
    }


def get_faers_term(drug_name):
    """Return the primary FAERS search term for a drug."""
    entry = DRUG_REGISTRY.get(drug_name)
    if entry:
        return entry["faers_terms"][0]
    return drug_name


if __name__ == "__main__":
    pos = get_positive_drugs()
    neg = get_negative_controls()
    print(f"Positive cases: {len(pos)} drugs")
    for name, info in pos.items():
        signals = ", ".join(info["expected_signals"][:2])
        print(f"  {name} ({info['brand']}) — expecting: {signals}")
    print(f"\nNegative controls: {len(neg)} drugs")
    for name, info in neg.items():
        print(f"  {name} ({info['brand']}) — expecting: no novel signals")
    print(f"\nTotal: {len(pos) + len(neg)} drugs in evaluation set")