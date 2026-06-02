"""
agent/graph.py
--------------
LangGraph agent — 3-node reasoning loop with 2 conditional edges.

This is what makes the project AGENTIC, not just a pipeline.

Pipeline (Phases 1-3): same steps every time.
  detect → check label → search pubmed → synthesize

Agent (Phase 4): DECIDES what to do based on what it finds.
  detect → triage → [need more info? → deeper search] → synthesize/abstain

The 3 nodes:
  1. signal_triage  — for each signal, assess evidence availability
  2. deep_search    — broader PubMed search when evidence is thin
  3. synthesize_or_abstain — generate report OR say "insufficient evidence"

The 2 conditional edges:
  1. After triage: enough evidence → synthesize, thin evidence → deep_search
  2. After synthesis: more signals → loop to triage, all done → end

Interview answer:
  "The fixed pipeline runs the same 4 steps for every signal.
   The agent looks at each signal's evidence and decides: is this
   enough to generate a report, or should I search deeper first?
   For signals with no literature support, it abstains rather than
   hallucinating. That decision loop is what makes it agentic."
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.state import SignalState
from agent.tools import (
    tool_detect_signals,
    tool_fetch_label,
    tool_check_label_gap,
    tool_search_pubmed,
    tool_search_pubmed_deep,
    tool_synthesize_report,
)


# ── Node 1: Signal Triage ────────────────────────────────────────

def signal_triage_node(state: dict) -> dict:
    """
    For the current signal: check label gap + initial PubMed search.
    Decide if evidence is sufficient or needs deeper search.
    """
    drug = state["drug_name"]
    idx = state["current_signal_index"]
    flagged = state["flagged_signals"]

    if idx >= len(flagged):
        return {**state, "processing_complete": True}

    signal = flagged[idx]
    event = signal["event"]
    print(f"\n  [Triage] Signal {idx+1}/{len(flagged)}: {event} (PRR={signal['prr']})")

    # Check label gap
    gap = tool_check_label_gap(event, state["label_sections"], drug)
    print(f"    Label: {gap['status']} (score={gap['match_score']})")

    # Initial PubMed search
    articles = tool_search_pubmed(drug, event, max_results=5)
    print(f"    PubMed: {articles_count} articles" if (articles_count := len(articles)) else "    PubMed: 0 articles")

    # Store results
    label_gaps = state.get("label_gaps", [])
    label_gaps.append(gap)

    pubmed_results = state.get("pubmed_results", [])
    pubmed_results.append(articles)

    # Decision: enough evidence or need deeper search?
    needs_deep = (
        len(articles) < 2
        and gap.get("status") == "novel"
        and signal.get("is_serious", False)
    )

    deeper_list = state.get("signals_needing_deeper_search", [])
    if needs_deep:
        deeper_list.append(idx)
        print(f"    Decision: NEED DEEPER SEARCH (novel + serious + thin evidence)")
    else:
        print(f"    Decision: Evidence sufficient for synthesis")

    return {
        **state,
        "label_gaps": label_gaps,
        "pubmed_results": pubmed_results,
        "signals_needing_deeper_search": deeper_list,
    }


# ── Node 2: Deep Search ─────────────────────────────────────────

def deep_search_node(state: dict) -> dict:
    """
    For signals flagged as needing more evidence, do a broader PubMed search.
    This is the agent's "I need more information" action.
    """
    drug = state["drug_name"]
    idx = state["current_signal_index"]
    signal = state["flagged_signals"][idx]
    event = signal["event"]

    print(f"\n  [Deep Search] {event} — broadening PubMed query...")

    articles = tool_search_pubmed_deep(drug, event, max_results=10)
    print(f"    Found {len(articles)} articles (deep search)")

    # Update the stored articles for this signal
    pubmed_results = state.get("pubmed_results", [])
    if idx < len(pubmed_results):
        pubmed_results[idx] = articles
    else:
        pubmed_results.append(articles)

    return {**state, "pubmed_results": pubmed_results}


# ── Node 3: Synthesize or Abstain ────────────────────────────────

def synthesize_or_abstain_node(state: dict) -> dict:
    """
    Generate an LLM evidence report OR abstain if evidence is still
    insufficient after deep search.

    Abstention is the most important feature for healthcare:
    "I don't know" is better than a hallucinated answer.
    """
    idx = state["current_signal_index"]
    signal = state["flagged_signals"][idx]
    event = signal["event"]
    gap = state["label_gaps"][idx]
    articles = state["pubmed_results"][idx]

    evidence_reports = state.get("evidence_reports", [])
    abstained = state.get("abstained_signals", [])
    escalated = state.get("escalated_signals", [])

    # Abstention gate: if still < 1 article AND novel, abstain
    if len(articles) < 1 and gap.get("status") == "novel":
        print(f"\n  [Abstain] {event} — insufficient evidence, marking inconclusive")
        abstained.append({
            "event": event,
            "prr": signal["prr"],
            "reason": "No published literature found to corroborate FAERS signal",
            "recommendation": "Flag for manual pharmacovigilance review",
        })
        evidence_reports.append({
            "drug": state["drug_name"],
            "event": event,
            "evidence_grade": "Inconclusive",
            "prr": signal["prr"],
            "label_status": gap.get("status"),
            "pubmed_count": 0,
            "abstained": True,
            "mechanism": "Insufficient evidence to determine mechanism",
            "recommendation": "Manual review required — no published corroboration found",
            "is_actionable": False,
        })
    else:
        # Synthesize report via LLM
        print(f"\n  [Synthesize] {event}")
        report = tool_synthesize_report(signal, gap, articles)
        if report:
            evidence_reports.append(report)
            # Check if this should be escalated
            if (gap.get("status") == "novel"
                    and report.get("evidence_grade") in ["Strong", "Moderate"]
                    and report.get("is_actionable")):
                escalated.append(report)
                print(f"    >>> ESCALATED: novel signal with {report['evidence_grade']} evidence")
        else:
            evidence_reports.append({
                "drug": state["drug_name"],
                "event": event,
                "evidence_grade": "Error",
                "prr": signal["prr"],
                "label_status": gap.get("status"),
                "abstained": False,
                "mechanism": "LLM synthesis failed",
                "is_actionable": False,
            })

    # Move to next signal
    return {
        **state,
        "evidence_reports": evidence_reports,
        "abstained_signals": abstained,
        "escalated_signals": escalated,
        "current_signal_index": idx + 1,
    }


# ── Conditional edge functions ───────────────────────────────────

def should_deep_search(state: dict) -> str:
    """
    Conditional edge after triage.
    If current signal needs deeper search → "deep_search"
    Otherwise → "synthesize"
    """
    idx = state["current_signal_index"]
    needs_deep = state.get("signals_needing_deeper_search", [])
    if idx in needs_deep:
        return "deep_search"
    return "synthesize"


def should_continue(state: dict) -> str:
    """
    Conditional edge after synthesis.
    If more signals to process → "triage" (loop back)
    If all done → "end"
    """
    if state.get("processing_complete"):
        return "end"
    idx = state["current_signal_index"]
    total = len(state["flagged_signals"])
    if idx < total:
        return "triage"
    return "end"


# ── Build the graph ──────────────────────────────────────────────

def build_agent_graph():
    """
    Build the LangGraph state machine.

    Graph structure:
        START → triage → [deep_search OR synthesize] → triage (loop) → END
    """
    try:
        from langgraph.graph import StateGraph, END

        graph = StateGraph(dict)

        # Add nodes
        graph.add_node("triage", signal_triage_node)
        graph.add_node("deep_search", deep_search_node)
        graph.add_node("synthesize", synthesize_or_abstain_node)

        # Set entry point
        graph.set_entry_point("triage")

        # Conditional edge 1: triage → deep_search OR synthesize
        graph.add_conditional_edges(
            "triage",
            should_deep_search,
            {
                "deep_search": "deep_search",
                "synthesize": "synthesize",
            }
        )

        # deep_search always → synthesize
        graph.add_edge("deep_search", "synthesize")

        # Conditional edge 2: synthesize → triage (loop) OR end
        graph.add_conditional_edges(
            "synthesize",
            should_continue,
            {
                "triage": "triage",
                "end": END,
            }
        )

        return graph.compile()

    except ImportError:
        print("[!] langgraph not installed. Install with: pip install langgraph")
        print("    Falling back to sequential pipeline.")
        return None


# ── Main run function ────────────────────────────────────────────

def run_agent(drug_name, date_end=None, max_signals=5):
    """
    Run the full pharmacovigilance agent for a drug.

    This is the top-level entry point.
    Returns the final state with all reports.
    """
    print(f"\n{'='*65}")
    print(f"PHARMASIGNAL AGENT: {drug_name}")
    if date_end:
        print(f"Mode: Retrospective (data up to {date_end})")
    print(f"{'='*65}")

    # Step 1: Detect signals
    print("\n[Phase 1-2] Signal Detection...")
    all_signals, flagged = tool_detect_signals(drug_name, date_end=date_end)
    flagged = flagged[:max_signals]  # cap for LLM cost control
    print(f"  {len(flagged)} signals to process (capped at {max_signals})")

    if not flagged:
        print("  No signals detected. Drug appears safe in FAERS data.")
        return {"drug_name": drug_name, "flagged_signals": [], "evidence_reports": []}

    # Step 2: Fetch label
    print("\n[Phase 1] Fetching drug label...")
    label = tool_fetch_label(drug_name)

    # Step 3: Build initial state
    initial_state = {
        "drug_name": drug_name,
        "date_end": date_end,
        "all_signals": all_signals,
        "flagged_signals": flagged,
        "current_signal_index": 0,
        "label_sections": label,
        "label_gaps": [],
        "pubmed_results": [],
        "evidence_reports": [],
        "signals_needing_deeper_search": [],
        "abstained_signals": [],
        "escalated_signals": [],
        "processing_complete": False,
        "error": None,
    }

    # Step 4: Run agent graph or fallback to sequential
    graph = build_agent_graph()

    if graph:
        print("\n[Phase 4] Running LangGraph agent loop...")
        final_state = graph.invoke(initial_state)
    else:
        print("\n[Phase 3] Running sequential pipeline (no LangGraph)...")
        final_state = _run_sequential(initial_state)

    # Step 5: Print results
    _print_final_report(final_state)

    return final_state


def _run_sequential(state):
    """Fallback: run triage → synthesize for each signal without LangGraph."""
    while state["current_signal_index"] < len(state["flagged_signals"]):
        state = signal_triage_node(state)
        if state.get("processing_complete"):
            break
        edge = should_deep_search(state)
        if edge == "deep_search":
            state = deep_search_node(state)
        state = synthesize_or_abstain_node(state)
    return state


def _print_final_report(state):
    """Print the final agent report."""
    drug = state["drug_name"]
    reports = state.get("evidence_reports", [])
    abstained = state.get("abstained_signals", [])
    escalated = state.get("escalated_signals", [])

    print(f"\n{'='*65}")
    print(f"FINAL REPORT: {drug}")
    print(f"{'='*65}")

    if not reports:
        print("No signals processed.")
        return

    for i, r in enumerate(reports, 1):
        novel_tag = " [NOVEL]" if r.get("label_status") == "novel" else ""
        abstain_tag = " [ABSTAINED]" if r.get("abstained") else ""
        print(f"\n  [{i}] {r.get('event', '?')}{novel_tag}{abstain_tag}")
        print(f"      PRR: {r.get('prr', '?')} | Grade: {r.get('evidence_grade', '?')}")
        if r.get("mechanism"):
            print(f"      Mechanism: {str(r['mechanism'])[:120]}")
        if r.get("recommendation"):
            print(f"      Action: {str(r['recommendation'])[:120]}")

    print(f"\n  SUMMARY:")
    print(f"    Signals processed: {len(reports)}")
    print(f"    Abstained: {len(abstained)}")
    print(f"    Escalated: {len(escalated)}")
    novel_count = sum(1 for r in reports if r.get("label_status") == "novel")
    print(f"    Novel signals: {novel_count}")


# ── Test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test 1: Current data
    state = run_agent("rosiglitazone", max_signals=3)

    # Test 2: Retrospective
    print("\n\n")
    state_retro = run_agent("rosiglitazone", date_end="20070101", max_signals=3)

    print("\n✓ agent/graph.py working")
