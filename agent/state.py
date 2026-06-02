"""
agent/state.py
--------------
LangGraph state schema for the pharmacovigilance agent.

The state carries all information through the reasoning loop:
signal data, label gaps, PubMed evidence, LLM reports, and
decisions about what to do next.
"""

from typing import TypedDict, Optional


class SignalState(TypedDict):
    """State for processing a single drug through the agent."""

    # Input
    drug_name: str
    date_end: Optional[str]  # retrospective cutoff

    # Phase 2 output — signal detection
    all_signals: list  # all computed signals
    flagged_signals: list  # Evans' criteria met
    current_signal_index: int  # which signal we're processing

    # Phase 3 output — per-signal context
    label_sections: dict  # from DailyMed
    label_gaps: list  # novel/known for each flagged signal
    pubmed_results: list  # articles per signal
    evidence_reports: list  # LLM synthesis per signal

    # Agent decisions
    signals_needing_deeper_search: list  # thin evidence, search more
    abstained_signals: list  # insufficient evidence
    escalated_signals: list  # strong novel signals

    # Control flow
    processing_complete: bool
    error: Optional[str]
