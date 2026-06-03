"""
openFDA FAERS API Client — v2 (with gap fixes)
================================================
Person A owns this file.

Changes from v1:
- Addition 1: Multi-name OR queries (Gap 1 fix)
- Addition 3: Co-medication lookup (Gap 2 fix)
- Both use single API calls, not loops

API docs: https://open.fda.gov/apis/drug/event/
"""

import requests
import json
import time
import hashlib
import os
from config import FAERS_BASE_URL, FAERS_CACHE_DIR


class FAERSClient:
    
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.last_request_time = 0
        os.makedirs(FAERS_CACHE_DIR, exist_ok=True)

    def _rate_limit(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < 0.3:
            time.sleep(0.3 - elapsed)
        self.last_request_time = time.time()

    def _cache_path(self, params):
        key = json.dumps(params, sort_keys=True)
        h = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(FAERS_CACHE_DIR, f"{h}.json")

    def _get(self, params):
        path = self._cache_path(params)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)

        self._rate_limit()
        if self.api_key:
            params["api_key"] = self.api_key

        resp = requests.get(FAERS_BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        with open(path, "w") as f:
            json.dump(data, f)

        return data

    # ──────────────────────────────────────────────
    # GAP 1 FIX: Build an OR query from multiple names
    # instead of merging separate queries (avoids double-counting).
    # "rosiglitazone" OR "rosiglitazone maleate" OR "avandia"
    # ──────────────────────────────────────────────
    def _build_drug_search(self, drug_name, date_end=None):
        """
        Build a FAERS search string that covers all name variants.
        Uses OR within a single query so FAERS deduplicates internally.
        """
        from data.drug_names import DRUG_REGISTRY

        drug_info = DRUG_REGISTRY.get(drug_name.lower(), {})
        faers_terms = drug_info.get("faers_terms", [drug_name])

        # Build OR query: ("term1" OR "term2" OR "term3")
        # This is a SINGLE query — no double-counting
        if len(faers_terms) == 1:
            drug_clause = f'patient.drug.medicinalproduct:"{faers_terms[0]}"'
        else:
            or_parts = " ".join(f'"{t}"' for t in faers_terms)
            drug_clause = f"patient.drug.medicinalproduct:({or_parts})"

        search = drug_clause
        if date_end:
            search += f" AND receivedate:[19900101 TO {date_end}]"

        return search
    
    NON_CLINICAL_MEDDRA = {
        "drug ineffective",
        "contraindicated product administered", 
        "off label use",
        "drug interaction",
        "therapeutic product effect decreased",
        "product use issue",
        "drug administered to patient of inappropriate age",
        "incorrect dose administered",
        "drug dispensing error",
        "intentional product misuse",
        "product substitution issue",
    }
    
    def get_event_counts(self, drug_name, date_end=None, limit=100):
        """
        Get adverse event counts for a drug (all name variants combined).
        Uses OR query so FAERS deduplicates — no double-counting.
        """
        search = self._build_drug_search(drug_name, date_end)

        params = {
            "search": search,
            "count": "patient.reaction.reactionmeddrapt.exact",
            "limit": min(limit, 1000),
        }

        try:
            data = self._get(params)
            results = data.get("results", [])           # ← store first
            return [                                     # ← then filter, then return
                r for r in results
                if r["term"].lower() not in NON_CLINICAL_MEDDRA
            ]
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"  [!] No FAERS results for '{drug_name}'")
                return []
            raise

    def get_serious_event_counts(self, drug_name, date_end=None, limit=50):
        """Get event counts filtered to serious outcome reports only."""
        search = self._build_drug_search(drug_name, date_end)
        # serious=1 means death/hospitalisation/life-threatening/disability
        search += " AND serious:1"
    
        params = {
        "search": search,
        "count": "patient.reaction.reactionmeddrapt.exact",
        "limit": min(limit, 1000),
        }
        try:
            data = self._get(params)
            return data.get("results", [])
        except requests.exceptions.HTTPError:
            return []
        
    def get_total_drug_reports(self, drug_name, date_end=None):
        """Total FAERS reports mentioning this drug (any name variant)."""
        search = self._build_drug_search(drug_name, date_end)
        params = {"search": search, "limit": 1}

        try:
            data = self._get(params)
            return data.get("meta", {}).get("results", {}).get("total", 0)
        except requests.exceptions.HTTPError:
            return 0

    def get_total_event_reports(self, event_name, date_end=None):
        """Total FAERS reports for this event across all drugs."""
        search = f'patient.reaction.reactionmeddrapt.exact:"{event_name}"'
        if date_end:
            search += f" AND receivedate:[19900101 TO {date_end}]"

        params = {"search": search, "limit": 1}

        try:
            data = self._get(params)
            return data.get("meta", {}).get("results", {}).get("total", 0)
        except requests.exceptions.HTTPError:
            return 0

    def get_total_database_size(self, date_end=None):
        """Approximate total reports in FAERS."""
        if date_end:
            search = f"receivedate:[19900101 TO {date_end}]"
        else:
            search = "receivedate:[19900101 TO 20261231]"

        params = {"search": search, "limit": 1}

        try:
            data = self._get(params)
            return data.get("meta", {}).get("results", {}).get("total", 0)
        except requests.exceptions.HTTPError:
            return 20_000_000

    # ──────────────────────────────────────────────
    # GAP 2 FIX: Co-medication lookup
    # One API call per flagged signal. Cacheable.
    # ──────────────────────────────────────────────
    def get_co_medications(self, drug_name, event_name, date_end=None, limit=10):
        """
        For reports mentioning drug + event, what other drugs appear most?
        Returns list of {term, count} for co-prescribed medications.

        Used to flag confounding: if 70% of MI reports also mention
        metformin, the signal may reflect the patient population
        (diabetics) rather than the drug itself.
        """
        from data.drug_names import DRUG_REGISTRY

        drug_info = DRUG_REGISTRY.get(drug_name.lower(), {})
        faers_terms = drug_info.get("faers_terms", [drug_name])

        # Search: reports with this drug AND this event
        if len(faers_terms) == 1:
            drug_clause = f'patient.drug.medicinalproduct:"{faers_terms[0]}"'
        else:
            or_parts = " ".join(f'"{t}"' for t in faers_terms)
            drug_clause = f"patient.drug.medicinalproduct:({or_parts})"

        search = f'{drug_clause} AND patient.reaction.reactionmeddrapt.exact:"{event_name}"'
        if date_end:
            search += f" AND receivedate:[19900101 TO {date_end}]"

        params = {
            "search": search,
            "count": "patient.drug.medicinalproduct.exact",
            "limit": limit + len(faers_terms),  # extra to filter self out
        }

        try:
            data = self._get(params)
            results = data.get("results", [])

            # Remove the drug itself from co-medication list
            co_meds = []
            for item in results:
                term_lower = item["term"].lower()
                is_self = any(ft.lower() in term_lower or term_lower in ft.lower()
                              for ft in faers_terms)
                if not is_self:
                    co_meds.append(item)

            return co_meds[:limit]

        except requests.exceptions.HTTPError:
            return []

    # ──────────────────────────────────────────────
    # GAP 4 PARTIAL FIX: Sex-stratified counts
    # Age is unreliable in FAERS so we skip it.
    # ──────────────────────────────────────────────
    def get_event_counts_by_sex(self, drug_name, event_name, date_end=None):
        """
        Get report counts for drug+event stratified by patient sex.
        Returns {"male": count, "female": count, "unknown": count}

        Sex codes in FAERS: 1=male, 2=female, 0=unknown
        """
        search_base = self._build_drug_search(drug_name, date_end)
        search_base += f' AND patient.reaction.reactionmeddrapt.exact:"{event_name}"'

        results = {}
        for sex_label, sex_code in [("male", "1"), ("female", "2")]:
            search = search_base + f" AND patient.patientsex:{sex_code}"
            params = {"search": search, "limit": 1}

            try:
                data = self._get(params)
                results[sex_label] = data.get("meta", {}).get("results", {}).get("total", 0)
            except requests.exceptions.HTTPError:
                results[sex_label] = 0

        return results


# ── SELF-TEST ──
if __name__ == "__main__":
    client = FAERSClient()

    print("=" * 65)
    print("TEST 1: Multi-name query — rosiglitazone (all variants)")
    print("=" * 65)
    events = client.get_event_counts("rosiglitazone", limit=10)
    if events:
        print(f"\n{'Event':<40} {'Count':>8}")
        print("-" * 50)
        for e in events:
            print(f"{e['term']:<40} {e['count']:>8}")
        total = client.get_total_drug_reports("rosiglitazone")
        print(f"\nTotal reports (all variants): {total:,}")

    print("\n")
    print("=" * 65)
    print("TEST 2: Retrospective — pre-2007")
    print("=" * 65)
    events_pre = client.get_event_counts("rosiglitazone", date_end="20070101", limit=15)
    if events_pre:
        print(f"\n{'Event':<40} {'Count':>8}")
        print("-" * 50)
        for e in events_pre:
            print(f"{e['term']:<40} {e['count']:>8}")

    print("\n")
    print("=" * 65)
    print("TEST 3: Co-medications for rosiglitazone + MI")
    print("=" * 65)
    co_meds = client.get_co_medications("rosiglitazone", "Myocardial infarction", limit=10)
    if co_meds:
        total_mi = client.get_total_drug_reports("rosiglitazone")
        print(f"\nTop co-prescribed drugs in MI reports:")
        for cm in co_meds:
            print(f"  {cm['term']:<30} {cm['count']:>6} reports")
        print("  (High overlap may indicate confounding by indication)")

    print("\n")
    print("=" * 65)
    print("TEST 4: Sex-stratified counts for rosiglitazone + MI")
    print("=" * 65)
    sex_data = client.get_event_counts_by_sex("rosiglitazone", "Myocardial infarction")
    print(f"  Male:   {sex_data.get('male', 0):,} reports")
    print(f"  Female: {sex_data.get('female', 0):,} reports")

    print("\n")
    print("=" * 65)
    print("TEST 5: Negative control — lisinopril")
    print("=" * 65)
    events_lis = client.get_event_counts("lisinopril", limit=10)
    if events_lis:
        print(f"\n{'Event':<40} {'Count':>8}")
        print("-" * 50)
        for e in events_lis:
            print(f"{e['term']:<40} {e['count']:>8}")

    db_size = client.get_total_database_size()
    print(f"\nTotal FAERS database: {db_size:,}")
    print("\nDone. Cache saved to cache/faers/")
