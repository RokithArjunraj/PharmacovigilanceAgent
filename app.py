"""
app.py — Streamlit Demo UI
============================
Two tabs:
  Tab 1: Signal Detection — enter a drug, see flagged signals with evidence reports
  Tab 2: Follow-up Prioritisation — see ranked follow-up queue with draft messages

Run: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


st.set_page_config(
    page_title="PharmaSignal",
    page_icon="🔬",
    layout="wide",
)

st.title("🔬 PharmaSignal")
st.caption("Pharmacovigilance Signal Detection & Follow-Up Prioritisation")

tab1, tab2, tab3 = st.tabs(["Signal Detection", "Follow-Up Priority", "About"])


# ── Tab 1: Signal Detection ──────────────────────────────────────

with tab1:
    st.header("Drug Safety Signal Detection")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        drug_name = st.text_input("Drug name", value="rosiglitazone",
                                   placeholder="Enter generic drug name")
    with col2:
        retrospective = st.checkbox("Retrospective mode", value=False)
        date_end = None
        if retrospective:
            date_end = st.text_input("Cutoff date (YYYYMMDD)", value="20070101")
    with col3:
        max_signals = st.slider("Max signals to analyse", 3, 15, 5)

    if st.button("Run Signal Detection", type="primary"):
        with st.spinner("Querying FAERS and computing signals..."):
            try:
                from signals.compute_signals import detect_signals
                signals = detect_signals(drug_name, date_end=date_end,
                                        top_n=50, verbose=False, enrich=False)
                flagged = [s for s in signals if s["flagged"]]

                st.success(f"Found {len(flagged)} flagged signals out of {len(signals)} events")

                # Signal table
                if flagged:
                    df = pd.DataFrame(flagged)
                    display_cols = ["event", "count", "prr", "ror", "chi_squared",
                                   "is_serious", "threshold_used", "composite_score"]
                    available_cols = [c for c in display_cols if c in df.columns]
                    st.dataframe(df[available_cols], use_container_width=True)

                    # Evidence synthesis for top signals
                    st.subheader("Evidence Reports")
                    with st.spinner("Fetching labels, PubMed, and running LLM synthesis..."):
                        from rag.synthesize_report import synthesize_all_signals
                        from data.fetch_label import fetch_label_sections

                        label = fetch_label_sections(drug_name)
                        reports = synthesize_all_signals(drug_name, flagged, label,
                                                        max_signals=max_signals)
                

                        for r in reports:
                            novel = "🆕 NOVEL" if r.get("label_status") == "novel" else "📋 Known"
                            grade = r.get("evidence_grade", "?")

                            with st.expander(f"{r.get('event', '?')} — {grade} | {novel}"):
                                col_a, col_b, col_c = st.columns(3)
                                col_a.metric("PRR", r.get("prr", "?"))
                                col_b.metric("Evidence Grade", grade)
                                col_c.metric("PubMed Hits", r.get("pubmed_count", 0))

                                if r.get("mechanism"):
                                    st.write(f"**Mechanism:** {r['mechanism']}")
                                if r.get("clinical_significance"):
                                    st.write(f"**Significance:** {r['clinical_significance']}")
                                if r.get("recommendation"):
                                    st.write(f"**Recommendation:** {r['recommendation']}")
                                if r.get("abstention_reason"):
                                    st.warning(f"Abstained: {r['abstention_reason']}")
                                if r.get("key_citations"):
                                    st.write("**Citations:**")
                                    for cite in r["key_citations"][:5]:
                                        st.write(f"- {cite}")   

                    # Store for Tab 2
                    st.session_state["flagged"] = flagged
                    st.session_state["reports"] = reports
                    st.session_state["drug"] = drug_name

            except Exception as e:
                st.error(f"Error: {e}")
                import traceback
                st.code(traceback.format_exc())


# ── Tab 2: Follow-Up Priority ────────────────────────────────────

with tab2:
    st.header("Follow-Up Prioritisation")

    if "flagged" not in st.session_state:
        st.info("Run signal detection in Tab 1 first.")
    else:
        flagged = st.session_state["flagged"]
        reports = st.session_state.get("reports", [])
        drug = st.session_state.get("drug", "?")

        st.write(f"Drug: **{drug}** | Signals: **{len(flagged)}**")

        try:
            from followup.score_priority import rank_followup_priorities, filter_top_priority

            # Build label gaps from reports
            label_gaps = [{"status": r.get("label_status", "unknown"),
                          "match_score": 0} for r in reports]

            priorities = rank_followup_priorities(
                flagged[:len(reports)], label_gaps, reports
            )
            filtered, stats = filter_top_priority(priorities, top_pct=0.5)

            st.metric("Follow-up volume reduction",
                     f"{stats.get('reduction_pct', 0)}%",
                     delta=f"-{stats.get('removed', 0)} signals")

            if filtered:
                df_p = pd.DataFrame(filtered)
                display_cols = ["event", "priority_tier", "priority_score",
                               "prr", "label_status", "evidence_grade"]
                available_cols = [c for c in display_cols if c in df_p.columns]
                st.dataframe(df_p[available_cols], use_container_width=True)

                # Generate messages
                if st.button("Generate Follow-Up Messages"):
                    with st.spinner("Generating messages..."):
                        from followup.generate_message import generate_batch_messages
                        messages = generate_batch_messages(filtered, max_messages=3)

                        for msg in messages:
                            urgency = msg.get("urgency", "routine").upper()
                            with st.expander(f"[{urgency}] {msg.get('event', '?')}"):
                                st.write(f"**Subject:** {msg.get('subject', 'N/A')}")
                                st.write(msg.get("body", ""))

        except Exception as e:
            st.error(f"Error: {e}")


# ── Tab 3: About ─────────────────────────────────────────────────

with tab3:
    st.header("About PharmaSignal")

    st.markdown("""
    ### What This Does

    PharmaSignal is an agentic RAG system for pharmacovigilance signal detection.
    It takes a drug name and:

    1. **Queries FDA FAERS** — adverse event reports from the real world
    2. **Computes disproportionality** — PRR, ROR, chi-squared to find statistical signals
    3. **Checks drug labels** — is this signal already documented or novel?
    4. **Searches PubMed** — published case reports and studies for corroboration
    5. **LLM synthesis** — generates evidence-graded reports with citations
    6. **Prioritises follow-up** — ranks incomplete reports for targeted outreach

    ### Data Sources

    - **openFDA FAERS API** — 20M+ adverse event reports
    - **DailyMed** — FDA-approved drug labels (SPL XML)
    - **PubMed E-utilities** — 35M+ biomedical abstracts

    ### Evaluation

    Retrospectively validated against 12 FDA Drug Safety Communications.
    The system is given only pre-warning FAERS data and checked for
    whether it would have detected the signal before the FDA acted.

    ### Tech Stack

    Python · Groq (LLaMA 3.1) · ChromaDB · sentence-transformers ·
    LangChain · LangGraph · RAGAS · Streamlit
    """)
