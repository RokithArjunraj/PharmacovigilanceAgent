# PharmaSignal 🔬

**End-to-End Pharmacovigilance Signal Detection & Follow-Up Prioritisation**

An agentic RAG system that detects emerging adverse drug events from FDA FAERS data, contextualises them against drug labels and published literature, and validates whether it could have caught real safety signals before the FDA issued warnings.

## The Problem

After a drug is approved, safety signals emerge from real-world use — sometimes years before regulators act. Vioxx was on the market for 5 years before withdrawal. This system cross-references adverse event reports with label text and published literature to identify *emerging discrepancies*: events reported more often than expected but not yet documented.

## Architecture

```
Drug Name
    │
    ▼
┌─────────────────────────┐
│  Phase 1: Data Layer    │  openFDA FAERS · DailyMed · PubMed
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  Phase 2: Signal Stats  │  PRR · ROR · Chi-squared · Evans' criteria
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  Phase 3: RAG Context   │  Label gap check · PubMed retrieval · LLM synthesis
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  Phase 4: Agent Loop    │  LangGraph: triage → deep search → synthesize/abstain
└────────────┬────────────┘
             ▼
┌─────────────────────────┐
│  Module 2: Follow-Up    │  Priority scoring · Draft message generation
└────────────┬────────────┘
             ▼
    Signal Intelligence Report
```

## Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/PharmacovigilanceAgent.git
cd PharmacovigilanceAgent

# Setup
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Config
cp config.py.example config.py
# Edit config.py — add your Groq API key (free at console.groq.com)

# Create cache directories
mkdir -p cache/faers cache/labels cache/pubmed cache/llm

# Test the pipeline
python -m data.fetch_faers            # FAERS API connection
python -m signals.compute_signals     # Signal detection
python -m rag.synthesize_report       # LLM evidence synthesis
python -m agent.graph                 # Full agent run

# Run evaluation
python -m evaluation.run_eval

# Launch UI
streamlit run app.py
```

## Evaluation

**Ground truth:** FDA Drug Safety Communications (12 drugs with known post-market warnings)

**Methodology:** Retrospective — system given only FAERS data from *before* the warning date

**Matching:** MedDRA System Organ Class root terms (not exact term matching)

| Metric | Result |
|--------|--------|
| Signal Recall (SOC-level) | 5/12 (42%) |
| Serious False Positives | 0/4 negative controls |
| Abstention Accuracy | Perfect on serious events |

### Why 42% recall is honest, not bad

The 7 misses fall into documented categories:
- **Insufficient pre-warning data** (dapagliflozin: 154 reports — too few for statistics)
- **Slow-onset events** (pioglitazone bladder cancer: takes 5-10 years to appear)
- **Abuse-pattern signals** (loperamide cardiac: abuse wasn't common pre-2016)
- **Common-event masking** (olmesartan diarrhoea: PRR ~1 because diarrhoea is universal)

These represent fundamental limitations of spontaneous reporting systems, not system failures.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Data | requests, pandas, lxml |
| Statistics | scipy, numpy |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Vector Store | ChromaDB |
| RAG | LangChain |
| LLM | Groq (llama-3.1-8b-instant) |
| Agent | LangGraph |
| Evaluation | RAGAS, custom metrics |
| UI | Streamlit |

## Data Sources

All free, no registration required:
- **openFDA FAERS API** — 20M+ adverse event reports
- **DailyMed API** — FDA-approved drug labels (SPL XML)
- **PubMed E-utilities** — 35M+ biomedical abstracts
- **FDA Drug Safety Communications** — evaluation ground truth

## Project Structure

```
├── data/
│   ├── fetch_faers.py          # openFDA FAERS API client
│   ├── fetch_label.py          # DailyMed label fetcher
│   ├── fetch_pubmed.py         # PubMed abstract fetcher
│   ├── drug_names.py           # Drug registry + ground truth
│   └── batch_cache.py          # Batch evaluation runner
├── signals/
│   ├── compute_signals.py      # PRR, ROR, Evans' criteria
│   ├── check_label_gap.py      # Novel vs known classification
│   ├── signal_ranker.py        # Report formatting
│   └── serious_outcomes.py     # Serious event list
├── rag/
│   ├── embed_abstracts.py      # ChromaDB + embeddings
│   └── synthesize_report.py    # Groq LLM evidence synthesis
├── agent/
│   ├── state.py                # LangGraph state schema
│   ├── tools.py                # Agent tool wrappers
│   └── graph.py                # 3-node reasoning loop
├── followup/
│   ├── score_priority.py       # Follow-up priority scoring
│   └── generate_message.py     # Draft message generation
├── evaluation/
│   └── run_eval.py             # Full evaluation pipeline
├── app.py                      # Streamlit UI
├── config.py.example           # Config template
└── requirements.txt
```

## Known Limitations & Future Work

- **Confounding by indication**: PRR doesn't adjust for baseline patient risk. Diabetes drugs show cardiac signals partly because diabetic patients have higher cardiac risk.
- **No temporal trends**: System uses aggregate counts, not time-series. A growing signal with low absolute count would be missed.
- **Single-event detection**: System checks events individually. Multi-event patterns (chronic diarrhoea + weight loss for olmesartan) require association analysis.
- **MedDRA hierarchy**: System uses keyword matching. Production system would use MedDRA's formal hierarchy to group related terms.
- **MCP integration**: Data sources could be exposed as MCP servers for interoperability with other pharmacovigilance agents.

## License

MIT
