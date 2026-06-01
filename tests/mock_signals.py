"""
tests/mock_signals.py
---------------------
Mock data so Person B can build and test independently.
Replace with real detect_signals() output once Person A is done.
"""

MOCK_ROSIGLITAZONE_SIGNALS = [
    {"drug": "rosiglitazone", "event": "Myocardial infarction",
     "count": 245, "prr": 3.82, "ror": 4.15, "chi_squared": 89.2, "flagged": True},
    {"drug": "rosiglitazone", "event": "Cardiac failure congestive",
     "count": 178, "prr": 2.91, "ror": 3.22, "chi_squared": 52.1, "flagged": True},
    {"drug": "rosiglitazone", "event": "Death",
     "count": 312, "prr": 1.1,  "ror": 1.15, "chi_squared": 2.3,  "flagged": False},
    {"drug": "rosiglitazone", "event": "Oedema peripheral",
     "count": 89,  "prr": 4.5,  "ror": 5.1,  "chi_squared": 41.0, "flagged": True},
    {"drug": "rosiglitazone", "event": "Hepatotoxicity",
     "count": 15,  "prr": 2.3,  "ror": 2.5,  "chi_squared": 5.1,  "flagged": True},
]

MOCK_CIPROFLOXACIN_SIGNALS = [
    {"drug": "ciprofloxacin", "event": "Tendon rupture",
     "count": 312, "prr": 5.2, "ror": 5.8, "chi_squared": 145.0, "flagged": True},
    {"drug": "ciprofloxacin", "event": "Peripheral neuropathy",
     "count": 198, "prr": 3.1, "ror": 3.4, "chi_squared": 67.3,  "flagged": True},
    {"drug": "ciprofloxacin", "event": "Aortic aneurysm",
     "count": 45,  "prr": 2.8, "ror": 3.0, "chi_squared": 18.2,  "flagged": True},
    {"drug": "ciprofloxacin", "event": "Nausea",
     "count": 890, "prr": 1.2, "ror": 1.3, "chi_squared": 1.8,   "flagged": False},
]

# Use this to test your files without waiting for Person A
def get_mock_signals(drug_name: str) -> list[dict]:
    registry = {
        "rosiglitazone": MOCK_ROSIGLITAZONE_SIGNALS,
        "ciprofloxacin": MOCK_CIPROFLOXACIN_SIGNALS,
    }
    return registry.get(drug_name.lower(), [])
