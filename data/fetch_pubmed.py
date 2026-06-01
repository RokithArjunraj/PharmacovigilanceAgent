"""
data/fetch_pubmed.py
--------------------
Fetches PubMed abstracts for a drug + adverse event combination.

Two chained API calls:
  1. esearch — get PMIDs matching the query
  2. efetch  — get full abstract text for those PMIDs

What you learn here:
  - Chained API calls where first response feeds second
  - Rate limiting to avoid being blocked
  - XML parsing where structure varies per article
  - Query construction for biomedical literature search
"""

import hashlib
import json
import time
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

CACHE_DIR = Path("data/pubmed_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

RATE_LIMIT_SLEEP = 0.35   # seconds between calls — stays under 3/sec limit


# ── Caching ───────────────────────────────────────────────────────────────────

def _cache_key(drug: str, event: str) -> str:
    raw = f"{drug.lower()}_{event.lower()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _load_cache(drug: str, event: str) -> list | None:
    p = CACHE_DIR / f"{_cache_key(drug, event)}.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


def _save_cache(drug: str, event: str, data: list):
    p = CACHE_DIR / f"{_cache_key(drug, event)}.json"
    with open(p, "w") as f:
        json.dump(data, f, indent=2)


# ── PubMed API calls ──────────────────────────────────────────────────────────

def _build_query(drug_name: str, event_name: str, strict: bool = True) -> str:
    """
    Build a PubMed query string.
    strict=True adds publication type filters for higher quality evidence.
    strict=False is the fallback when strict returns too few results.
    """
    base = f'("{drug_name}"[Title/Abstract]) AND ("{event_name}"[Title/Abstract])'
    if strict:
        pub_types = "(case reports[pt] OR clinical study[pt] OR review[pt] OR meta-analysis[pt])"
        return f"{base} AND {pub_types}"
    return base


def _search_pmids(query: str, max_results: int = 10) -> list[str]:
    """Run esearch, return list of PMIDs."""
    params = {
        "db":      "pubmed",
        "term":    query,
        "retmax":  max_results,
        "retmode": "json",
    }
    try:
        resp = requests.get(ESEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f"  PubMed esearch error: {e}")
        return []


def _fetch_abstracts(pmids: list[str]) -> list[dict]:
    """Run efetch for a list of PMIDs, parse XML, return abstract dicts."""
    if not pmids:
        return []

    params = {
        "db":      "pubmed",
        "id":      ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
    }
    try:
        resp = requests.get(EFETCH_URL, params=params, timeout=30)
        resp.raise_for_status()
        return _parse_pubmed_xml(resp.text)
    except Exception as e:
        print(f"  PubMed efetch error: {e}")
        return []


def _parse_pubmed_xml(xml_text: str) -> list[dict]:
    """
    Parse PubMed XML response into list of article dicts.

    PubMed XML structure:
      <PubmedArticleSet>
        <PubmedArticle>
          <MedlineCitation>
            <PMID>...</PMID>
            <Article>
              <ArticleTitle>...</ArticleTitle>
              <Abstract>
                <AbstractText Label="BACKGROUND">...</AbstractText>
                <AbstractText Label="RESULTS">...</AbstractText>
                ...or just <AbstractText>plain text</AbstractText>
              </Abstract>
              <AuthorList>...</AuthorList>
              <Journal>
                <Title>...</Title>
                <JournalIssue><PubDate><Year>...</Year></PubDate></JournalIssue>
              </Journal>
            </Article>
          </MedlineCitation>
        </PubmedArticle>
      </PubmedArticleSet>
    """
    articles = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  PubMed XML parse error: {e}")
        return []

    for article_el in root.findall(".//PubmedArticle"):
        try:
            pmid  = article_el.findtext(".//PMID", "")
            title = article_el.findtext(".//ArticleTitle", "")

            # Abstract — may have multiple labelled sections
            abstract_parts = []
            for ab in article_el.findall(".//AbstractText"):
                label = ab.get("Label", "")
                text  = (ab.text or "").strip()
                if text:
                    if label:
                        abstract_parts.append(f"{label}: {text}")
                    else:
                        abstract_parts.append(text)
            abstract = " ".join(abstract_parts)

            # Authors — first author surname + "et al" if multiple
            authors_els = article_el.findall(".//Author")
            authors = ""
            if authors_els:
                first = authors_els[0].findtext("LastName", "")
                authors = f"{first} et al." if len(authors_els) > 1 else first

            year    = article_el.findtext(".//PubDate/Year", "")
            journal = article_el.findtext(".//Journal/Title", "")

            pub_types = [
                el.text for el in article_el.findall(".//PublicationType")
                if el.text
            ]

            if abstract:  # skip articles with no abstract text
                articles.append({
                    "pmid":             pmid,
                    "title":            title,
                    "abstract":         abstract,
                    "authors":          authors,
                    "year":             year,
                    "journal":          journal,
                    "publication_types": pub_types,
                })
        except Exception:
            continue  # skip malformed entries silently

    return articles


# ── Public interface ──────────────────────────────────────────────────────────

def search_drug_event(drug_name: str, event_name: str,
                      max_results: int = 10) -> list[dict]:
    """
    Main function. Searches PubMed for articles about drug + adverse event.
    Returns list of article dicts with: pmid, title, abstract, authors,
    year, journal, publication_types.

    Falls back to unfiltered query if strict search returns < 3 results.
    Caches results to avoid repeated API calls during development.
    """
    # Check cache
    cached = _load_cache(drug_name, event_name)
    if cached is not None:
        print(f"  [cache] PubMed: {drug_name} + {event_name} ({len(cached)} articles)")
        return cached

    print(f"  Searching PubMed: '{drug_name}' + '{event_name}'...")

    # Try strict query first
    query  = _build_query(drug_name, event_name, strict=True)
    pmids  = _search_pmids(query, max_results)
    time.sleep(RATE_LIMIT_SLEEP)

    # Fallback to broad query if too few results
    if len(pmids) < 3:
        print(f"    Strict query returned {len(pmids)} results, trying broad query...")
        query = _build_query(drug_name, event_name, strict=False)
        pmids = _search_pmids(query, max_results)
        time.sleep(RATE_LIMIT_SLEEP)

    if not pmids:
        print(f"    No PubMed results found for {drug_name} + {event_name}")
        _save_cache(drug_name, event_name, [])
        return []

    articles = _fetch_abstracts(pmids)
    time.sleep(RATE_LIMIT_SLEEP)

    print(f"    Found {len(articles)} articles with abstracts")
    _save_cache(drug_name, event_name, articles)
    return articles


# ── Test ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Testing fetch_pubmed.py ===\n")

    # Test 1: well-known signal — should find Nissen 2007 meta-analysis
    print("Test 1: rosiglitazone + myocardial infarction")
    articles = search_drug_event("rosiglitazone", "myocardial infarction", max_results=5)
    for a in articles[:3]:
        print(f"  [{a['year']}] {a['authors']} — {a['title'][:70]}...")
        print(f"    Abstract: {a['abstract'][:150]}...\n")

    # Test 2: obscure signal — tests fallback logic
    print("\nTest 2: olmesartan + enteropathy (sparse results)")
    articles2 = search_drug_event("olmesartan", "enteropathy", max_results=5)
    print(f"  Found {len(articles2)} articles")

    print("\n✓ fetch_pubmed.py working")
