# PharmaSignal

End-to-end pharmacovigilance signal detection system.

Detects emerging adverse drug reaction signals from FDA FAERS data,
cross-references against official drug labels and published literature,
and prioritises follow-up data collection.

Built as part of Novartis case competition solution.

## Modules

- `data/`     — API clients: openFDA FAERS, DailyMed, PubMed
- `signals/`  — Statistical signal detection (PRR, ROR) + label gap analysis
- `rag/`      — ChromaDB embedding infrastructure + LLM evidence synthesis
- `followup/` — Follow-up prioritisation and message generation
- `tests/`    — Mock data and test scripts

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.py.example config.py   # add your Groq API key
```

## Team

- Person A — data layer + signal statistics
- Person B — label gap detection + RAG infrastructure
