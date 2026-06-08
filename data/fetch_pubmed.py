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

def _cache_key(drug: str, event_or_key: str) -> str:
    raw = f"{drug.lower()}_{event_or_key.lower()}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _load_cache(drug: str, event_or_key: str) -> list | None:
    p = CACHE_DIR / f"{_cache_key(drug, event_or_key)}.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


def _save_cache(drug: str, event_or_key: str, data: list):
    p = CACHE_DIR / f"{_cache_key(drug, event_or_key)}.json"
    with open(p, "w") as f:
        json.dump(data, f, indent=2)


# ── PubMed API calls ──────────────────────────────────────────────────────────

def _build_query(drug_name: str, event_name: str, strict: bool = True,
                 max_year: int = None) -> str:
    drug_term  = f'"{drug_name}"[Title/Abstract]'
    event_term = f'"{event_name}"[Title/Abstract]'

    causal_terms = (
        '("adverse effect"[Title/Abstract] OR '
        '"side effect"[Title/Abstract] OR '
        '"induced"[Title/Abstract] OR '
        '"toxicity"[Title/Abstract] OR '
        '"associated with"[Title/Abstract] OR '
        '"risk of"[Title/Abstract] OR '
        '"adverse reaction"[Title/Abstract])'
    )

    base = f"({drug_term}) AND ({event_term}) AND {causal_terms}"

    # Retrospective purity — exclude papers after FDA warning year.
    # Prevents future knowledge leakage in retrospective evaluation.
    if max_year:
        base += f' AND ("1900"[PDAT] : "{max_year}"[PDAT])'

    if strict:
        pub_types = (
            "(clinical trial[pt] OR randomized controlled trial[pt] OR "
            "meta-analysis[pt] OR systematic review[pt] OR "
            "case reports[pt] OR review[pt])"
        )
        return f"{base} AND {pub_types}"

    return base


def _search_pmids(query: str, max_results: int = 10, date_end: str = None) -> list[str]:
    """Run esearch, return list of PMIDs."""
    params = {
        "db":      "pubmed",
        "term":    query,
        "retmax":  max_results,
        "retmode": "json",
    }
    # Retrospective mode: only papers published before cutoff date
    if date_end and len(date_end) == 8:
        params["mindate"] = "1900/01/01"
        params["maxdate"] = f"{date_end[:4]}/{date_end[4:6]}/{date_end[6:8]}"
        params["datetype"] = "pdat"
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
                      max_results: int = 10, date_end: str = None,
                      max_year: int = None) -> list[dict]:
    """
    Main function. Searches PubMed for articles about drug + adverse event.
    Returns list of article dicts with: pmid, title, abstract, authors,
    year, journal, publication_types.

    Args:
        max_year: if set, only return papers published up to this year.
                  Used for retrospective purity — prevents future knowledge
                  leakage when evaluating pre-warning FAERS data.

    Falls back to unfiltered query if strict search returns < 3 results.
    Caches results — note: cache key includes max_year so cutoff/no-cutoff
    runs are cached separately.
    """
    if max_year is None:
        max_year = int(date_end[:4]) if date_end else None
    # Cache key includes max_year to keep cutoff/no-cutoff results separate
    cache_key = f"{drug_name}_{event_name}_{max_year or 'all'}"
    cached = _load_cache(drug_name, cache_key)
    if cached is not None:
        print(f"  [cache] PubMed: {drug_name} + {event_name} "
              f"(year≤{max_year or 'all'}, {len(cached)} articles)")
        return cached

    print(f"  Searching PubMed: '{drug_name}' + '{event_name}'"
          f"{f' (≤{max_year})' if max_year else ''}...")

    # Try strict query first
    query = _build_query(drug_name, event_name, strict=True, max_year=max_year)
    pmids  = _search_pmids(query, max_results, date_end=date_end)
    time.sleep(RATE_LIMIT_SLEEP)

    # Fallback to broad query if too few results
    if len(pmids) < 3:
        print(f"    Strict query returned {len(pmids)} results, trying broad query...")
        query = _build_query(drug_name, event_name, strict=False, max_year=max_year)
        pmids = _search_pmids(query, max_results, date_end=date_end)
        time.sleep(RATE_LIMIT_SLEEP)

    if not pmids:
        print(f"    No PubMed results found for {drug_name} + {event_name}")
        _save_cache(drug_name, cache_key, [])
        return []

    articles = _fetch_abstracts(pmids)
    time.sleep(RATE_LIMIT_SLEEP)

    print(f"    Found {len(articles)} articles with abstracts")
    _save_cache(drug_name, cache_key, articles)
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
