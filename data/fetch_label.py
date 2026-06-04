"""
data/fetch_label.py
-------------------
Fetches FDA drug label sections from DailyMed API.

What you learn here:
  - DailyMed returns SPL (Structured Product Labeling) XML
  - Each section is identified by a LOINC code
  - We extract plain text from the relevant safety sections
  - Cache aggressively — labels rarely change
"""

import json
import re
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

CACHE_DIR = Path("data/labels")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DAILYMED_SEARCH = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
DAILYMED_SPL    = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{setid}.xml"

# LOINC codes for safety-relevant sections
SECTION_CODES = {
    "indications_and_usage":     "34067-9",
    "boxed_warning":             "34066-1",
    "warnings_and_precautions":  "43685-7",
    "adverse_reactions":         "34084-4",
    "contraindications":         "34070-3",
    "drug_interactions":         "34073-7",
}

# XML namespace used in SPL documents
NS = {"hl7": "urn:hl7-org:v3"}


# ── Caching ───────────────────────────────────────────────────────────────────

def _cache_path(drug_name: str) -> Path:
    return CACHE_DIR / f"{drug_name.lower().replace(' ', '_')}.json"


def _load_cache(drug_name: str) -> dict | None:
    p = _cache_path(drug_name)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


def _save_cache(drug_name: str, data: dict):
    with open(_cache_path(drug_name), "w") as f:
        json.dump(data, f, indent=2)


# ── DailyMed API calls ────────────────────────────────────────────────────────

def _get_setid(drug_name: str) -> str | None:
    """
    Search DailyMed and return the setid of the most recently
    published label — not necessarily the brand.

    Why: 28 labels exist for azathioprine. Page 1 returns a random
    generic stub that may omit indications_and_usage. The most
    recently published label has the most complete, up-to-date sections
    regardless of manufacturer.
    """
    try:
        resp = requests.get(
            DAILYMED_SEARCH,
            params={"drug_name": drug_name, "pagesize": 10},
            timeout=15
        )
        resp.raise_for_status()
        results = resp.json().get("data", [])

        if not results:
            return None

        # Sort by published_date descending — most recent first
        def parse_date(r):
            from datetime import datetime
            try:
                return datetime.strptime(r.get("published_date", ""), "%b %d, %Y")
            except ValueError:
                return datetime.min

        results_sorted = sorted(results, key=parse_date, reverse=True)
        best = results_sorted[0]
        print(f"  [DailyMed] Using: {best['title']} ({best['published_date']})")
        return best["setid"]

    except Exception as e:
        print(f"  DailyMed search error for '{drug_name}': {e}")
    return None


# ── XML parsing ───────────────────────────────────────────────────────────────

def _extract_text_from_element(element) -> str:
    """
    Recursively extract all text from an XML element.
    SPL XML mixes text in <paragraph>, <item>, <content> etc.
    """
    parts = []
    if element.text and element.text.strip():
        parts.append(element.text.strip())
    for child in element:
        parts.append(_extract_text_from_element(child))
        if child.tail and child.tail.strip():
            parts.append(child.tail.strip())
    return " ".join(p for p in parts if p)


def _clean_text(text: str) -> str:
    """Remove XML artifacts and normalise whitespace."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\x20-\x7E]", "", text)  # remove non-ASCII
    return text.strip()


def _parse_sections(xml_text: str) -> dict:
    """
    Parse SPL XML → extract each safety section as plain text.
    Returns dict keyed by section name.
    """
    sections = {k: "" for k in SECTION_CODES}

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
        return sections

    # Build reverse map: loinc_code → section_name
    code_to_name = {v: k for k, v in SECTION_CODES.items()}

    # Walk all <section> elements
    for section_el in root.iter("{urn:hl7-org:v3}section"):
        code_el = section_el.find("hl7:code", NS)
        if code_el is None:
            continue
        loinc = code_el.get("code", "")
        if loinc in code_to_name:
            raw_text = _extract_text_from_element(section_el)
            sections[code_to_name[loinc]] = _clean_text(raw_text)

    return sections

def _fetch_xml(setid: str) -> str | None:
    """Download the full SPL XML for a given setid."""
    try:
        resp = requests.get(DAILYMED_SPL.format(setid=setid), timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  DailyMed XML fetch error for setid '{setid}': {e}")
    return None

# ── Public interface ──────────────────────────────────────────────────────────

def fetch_label_sections(drug_name: str) -> dict:
    """
    Main function. Returns dict with keys:
      boxed_warning, warnings_and_precautions, adverse_reactions,
      contraindications, drug_interactions
    Each value is plain text string (empty string if section not found).

    Caches result to data/labels/{drug_name}.json — labels don't change.
    """
    # Check cache first
    cached = _load_cache(drug_name)
    if cached:
        print(f"  [cache] label for '{drug_name}'")
        return cached

    print(f"  Fetching DailyMed label for '{drug_name}'...")

    setid = _get_setid(drug_name)
    if not setid:
        # Try brand name fallback or return empty
        print(f"  No setid found for '{drug_name}' — returning empty label")
        empty = {k: "" for k in SECTION_CODES}
        return empty

    time.sleep(0.5)  # be polite to DailyMed

    xml_text = _fetch_xml(setid)
    if not xml_text:
        return {k: "" for k in SECTION_CODES}

    sections = _parse_sections(xml_text)
    _save_cache(drug_name, sections)

    # Print summary
    for name, text in sections.items():
        status = f"{len(text)} chars" if text else "not found"
        print(f"    {name}: {status}")

    return sections


# ── Test ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Testing fetch_label.py ===\n")

    for drug in ["rosiglitazone", "ciprofloxacin", "metoclopramide"]:
        print(f"\nDrug: {drug}")
        sections = fetch_label_sections(drug)
        for name, text in sections.items():
            if text:
                print(f"  {name}: {text[:120]}...")

    print("\n✓ fetch_label.py working")
