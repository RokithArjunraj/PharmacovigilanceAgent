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
from logging import root
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
def _get_all_setids(drug_name: str) -> list[str]:
    """
    Get all setids for a drug from DailyMed.
    Fetches all pages.
    """
    setids = []
    page = 1
    while True:
        try:
            resp = requests.get(
                DAILYMED_SEARCH,
                params={"drug_name": drug_name, "pagesize": 10, "page": page},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("data", [])
            if not results:
                break
            setids.extend(r["setid"] for r in results)

            # Check if more pages exist
            if data["metadata"]["next_page"] == "null" or not data["metadata"].get("next_page_url"):
                break
            page += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  DailyMed pagination error: {e}")
            break

    print(f"  [DailyMed] Found {len(setids)} labels for '{drug_name}'")
    return setids

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
    # After LOINC match fails, try matching by title text
    TITLE_FALLBACKS = {
    "indications_and_usage":    ["indication", "indications"],
    "adverse_reactions":        ["adverse reaction", "adverse event", "side effect"],
    "warnings_and_precautions": ["warning", "precaution"],
    "boxed_warning":            ["boxed warning", "black box"],
    "contraindications":        ["contraindication"],
    "drug_interactions":        ["drug interaction"],
    }
    for section_el in root.iter("{urn:hl7-org:v3}section"):
        code_el = section_el.find("hl7:code", NS)
        loinc = code_el.get("code", "") if code_el is not None else ""
    
        if loinc in code_to_name:
            # Primary path — LOINC match
            section_name = code_to_name[loinc]
        else:
            # Fallback — match by section title text
            title_el = section_el.find("hl7:title", NS)
            title_text = (title_el.text or "").lower() if title_el is not None else ""
            section_name = None
            for name, keywords in TITLE_FALLBACKS.items():
                if any(kw in title_text for kw in keywords):
                    section_name = name
                    break
            if not section_name:
                continue
    
        raw_text = _extract_text_from_element(section_el)
        # Append rather than overwrite — multiple sections may match
        existing = sections.get(section_name, "")
        sections[section_name] = (existing + " " + _clean_text(raw_text)).strip()

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
    Fetch ALL available labels for a drug from DailyMed and merge
    their sections. Union of all ADRs and indications across all
    manufacturers — no single label is authoritative.
    """
    cached = _load_cache(drug_name)
    if cached:
        print(f"  [cache] label for '{drug_name}'")
        return cached

    print(f"  Fetching all DailyMed labels for '{drug_name}'...")

    # Get all setids for this drug
    setids = _get_all_setids(drug_name)
    if not setids:
        return {k: "" for k in SECTION_CODES}

    # Fetch and merge all labels
    merged = {k: set() for k in SECTION_CODES}  # use sets to deduplicate

    for setid in setids:
        xml_text = _fetch_xml(setid)
        if not xml_text:
            continue
        sections = _parse_sections(xml_text)
        for key, text in sections.items():
            if text.strip():
                merged[key].add(text.strip())
        time.sleep(0.3)  # rate limit

    # Join all unique section texts
    final = {k: " ".join(merged[k]) for k in SECTION_CODES}

    _save_cache(drug_name, final)
    return final





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

    sections = fetch_label_sections("azathioprine")
    print("indications:", sections["indications_and_usage"][:200])
    print("adverse_reactions:", sections["adverse_reactions"][:200])