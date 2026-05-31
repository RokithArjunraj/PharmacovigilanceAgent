"""
openFDA FAERS API Client
=========================
Person A owns this file.

Fetches adverse event report data from FDA's FAERS database.
Supports date filtering for retrospective (time-travel) evaluation.
All responses cached to disk to avoid rate limit issues.

API docs: https://open.fda.gov/apis/drug/event/
Rate limit: 240 req/min without key.
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
        """Wait between API calls to stay under rate limit."""
        elapsed = time.time() - self.last_request_time
        if elapsed < 0.3:
            time.sleep(0.3 - elapsed)
        self.last_request_time = time.time()

    def _cache_path(self, params):
        """Generate a cache filename from query parameters."""
        key = json.dumps(params, sort_keys=True)
        h = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(FAERS_CACHE_DIR, f"{h}.json")

    def _get(self, params):
        """Make a cached, rate-limited GET request."""
        # Check cache first
        path = self._cache_path(params)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)

        # Rate limit and request
        self._rate_limit()
        if self.api_key:
            params["api_key"] = self.api_key

        resp = requests.get(FAERS_BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # Save to cache
        with open(path, "w") as f:
            json.dump(data, f)

        return data

    def get_event_counts(self, drug_name, date_end=None, limit=100):
        """
        Get adverse event counts for a specific drug.

        Args:
            drug_name: Generic name, e.g. "rosiglitazone"
            date_end: Optional cutoff date "YYYYMMDD" for retrospective mode.
            limit: Max events to return (max 1000).

        Returns:
            List of dicts: [{"term": "Myocardial infarction", "count": 245}, ...]
        """
        search = f'patient.drug.medicinalproduct:"{drug_name}"'
        if date_end:
            search += f" AND receivedate:[19900101 TO {date_end}]"

        params = {
            "search": search,
            "count": "patient.reaction.reactionmeddrapt.exact",
            "limit": min(limit, 1000),
        }

        try:
            data = self._get(params)
            return data.get("results", [])
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"  [!] No FAERS results for '{drug_name}'")
                return []
            raise

    def get_total_drug_reports(self, drug_name, date_end=None):
        """
        Total FAERS reports mentioning this drug.
        This is (a + b) in the 2x2 contingency table.
        """
        search = f'patient.drug.medicinalproduct:"{drug_name}"'
        if date_end:
            search += f" AND receivedate:[19900101 TO {date_end}]"

        params = {"search": search, "limit": 1}

        try:
            data = self._get(params)
            return data.get("meta", {}).get("results", {}).get("total", 0)
        except requests.exceptions.HTTPError:
            return 0

    def get_total_event_reports(self, event_name, date_end=None):
        """
        Total FAERS reports mentioning this adverse event across all drugs.
        This is (a + c) in the 2x2 contingency table.
        """
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
        """
        Approximate total reports in the FAERS database.
        This is N in the 2x2 contingency table.
        """
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


# ── SELF-TEST ──
if __name__ == "__main__":
    client = FAERSClient()

    print("=" * 65)
    print("TEST 1: Top adverse events for rosiglitazone (all time)")
    print("=" * 65)

    events = client.get_event_counts("rosiglitazone", limit=20)
    if not events:
        print("FAILED — no results. Check your internet connection.")
    else:
        print(f"\n{'Event':<40} {'Count':>8}")
        print("-" * 50)
        for e in events:
            print(f"{e['term']:<40} {e['count']:>8}")

        total = client.get_total_drug_reports("rosiglitazone")
        print(f"\nTotal reports for rosiglitazone: {total:,}")

    print("\n")
    print("=" * 65)
    print("TEST 2: Retrospective — rosiglitazone before Jan 2007")
    print("=" * 65)

    events_pre = client.get_event_counts("rosiglitazone", date_end="20070101", limit=15)
    if events_pre:
        print(f"\n{'Event':<40} {'Count':>8}")
        print("-" * 50)
        for e in events_pre:
            print(f"{e['term']:<40} {e['count']:>8}")

        cardiac_terms = ["myocardial infarction", "cardiac failure", "cardiovascular"]
        found_cardiac = [
            e for e in events_pre
            if any(t in e["term"].lower() for t in cardiac_terms)
        ]
        if found_cardiac:
            print(f"\n  >>> CARDIAC SIGNALS VISIBLE in pre-2007 data:")
            for e in found_cardiac:
                print(f"      {e['term']}: {e['count']} reports")
            print("  >>> This is what the system should detect!")

    print("\n")
    print("=" * 65)
    print("TEST 3: Negative control — lisinopril")
    print("=" * 65)

    events_lis = client.get_event_counts("lisinopril", limit=10)
    if events_lis:
        print(f"\n{'Event':<40} {'Count':>8}")
        print("-" * 50)
        for e in events_lis:
            print(f"{e['term']:<40} {e['count']:>8}")

    print("\n")
    print("=" * 65)
    print("TEST 4: Database size")
    print("=" * 65)
    db_size = client.get_total_database_size()
    print(f"Total FAERS reports (all time): {db_size:,}")

    print("\n Done. Cache saved to cache/faers/")