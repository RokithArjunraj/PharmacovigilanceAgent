"""
Mock Signal Data — Person B develops against this.
"""

MOCK_ROSIGLITAZONE = [
    {"drug": "rosiglitazone", "event": "Myocardial infarction",
     "count": 245, "prr": 3.82, "ror": 4.15, "chi_squared": 89.2,
     "prr_ci_lower": 2.1, "prr_ci_upper": 6.9, "flagged": True},
    {"drug": "rosiglitazone", "event": "Cardiac failure congestive",
     "count": 178, "prr": 2.91, "ror": 3.22, "chi_squared": 52.1,
     "prr_ci_lower": 1.8, "prr_ci_upper": 4.7, "flagged": True},
    {"drug": "rosiglitazone", "event": "Oedema peripheral",
     "count": 89, "prr": 4.5, "ror": 5.1, "chi_squared": 41.0,
     "prr_ci_lower": 2.5, "prr_ci_upper": 8.1, "flagged": True},
    {"drug": "rosiglitazone", "event": "Death",
     "count": 312, "prr": 1.1, "ror": 1.15, "chi_squared": 2.3,
     "prr_ci_lower": 0.9, "prr_ci_upper": 1.4, "flagged": False},
    {"drug": "rosiglitazone", "event": "Nausea",
     "count": 67, "prr": 0.8, "ror": 0.75, "chi_squared": 1.2,
     "prr_ci_lower": 0.5, "prr_ci_upper": 1.3, "flagged": False},
]

MOCK_CIPROFLOXACIN = [
    {"drug": "ciprofloxacin", "event": "Tendon rupture",
     "count": 312, "prr": 8.7, "ror": 9.2, "chi_squared": 245.3,
     "prr_ci_lower": 5.1, "prr_ci_upper": 14.8, "flagged": True},
    {"drug": "ciprofloxacin", "event": "Tendon disorder",
     "count": 189, "prr": 6.1, "ror": 6.8, "chi_squared": 142.7,
     "prr_ci_lower": 3.8, "prr_ci_upper": 9.8, "flagged": True},
]

MOCK_LISINOPRIL = [
    {"drug": "lisinopril", "event": "Cough",
     "count": 2341, "prr": 3.2, "ror": 3.5, "chi_squared": 312.4,
     "prr_ci_lower": 2.8, "prr_ci_upper": 3.9, "flagged": True},
]


def get_mock_signals(drug_name):
    mocks = {
        "rosiglitazone": MOCK_ROSIGLITAZONE,
        "ciprofloxacin": MOCK_CIPROFLOXACIN,
        "lisinopril": MOCK_LISINOPRIL,
    }
    return mocks.get(drug_name, [])


def get_mock_flagged(drug_name):
    return [s for s in get_mock_signals(drug_name) if s["flagged"]]


if __name__ == "__main__":
    for drug in ["rosiglitazone", "ciprofloxacin", "lisinopril"]:
        flagged = get_mock_flagged(drug)
        print(f"\n{drug}: {len(flagged)} flagged signals")
        for s in flagged:
            print(f"  {s['event']}: PRR={s['prr']}, count={s['count']}")