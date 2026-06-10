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

# ── Custom CSS ────────────────────────────────────────────────────

st.markdown("""
<style>
/* Grade badges */
.grade-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
    margin-right: 6px;
}
.grade-strong { background: #d4edda; color: #155724; }
.grade-confirmed { background: #cce5ff; color: #004085; }
.grade-moderate { background: #fff3cd; color: #856404; }
.grade-weak { background: #f8d7da; color: #721c24; }
.grade-inconclusive { background: #e2e3e5; color: #383d41; }

/* Priority badges */
.priority-critical { background: #dc3545; color: white; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
.priority-high { background: #fd7e14; color: white; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
.priority-medium { background: #ffc107; color: #333; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
.priority-low { background: #6c757d; color: white; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }

/* Novel/Known tags */
.tag-novel { background: #e8f5e9; color: #2e7d32; padding: 2px 8px; border-radius: 8px; font-size: 12px; font-weight: 500; }
.tag-known { background: #e3f2fd; color: #1565c0; padding: 2px 8px; border-radius: 8px; font-size: 12px; font-weight: 500; }

/* Signal card */
.signal-card {
    border-left: 4px solid #dee2e6;
    padding: 12px 16px;
    margin-bottom: 8px;
    border-radius: 0 8px 8px 0;
    background: #f8f9fa;
}
.signal-card.critical { border-left-color: #dc3545; }
.signal-card.high { border-left-color: #fd7e14; }
.signal-card.medium { border-left-color: #ffc107; }
.signal-card.low { border-left-color: #6c757d; }

/* Recommended action box */
.action-box {
    border: 1px solid #dee2e6;
    border-radius: 8px;
    padding: 10px 14px;
    margin-top: 8px;
    font-size: 13px;
}
.action-urgent { border-color: #dc3545; background: #fff5f5; }
.action-monitor { border-color: #ffc107; background: #fffdf0; }
.action-routine { border-color: #28a745; background: #f0fff4; }
</style>
""", unsafe_allow_html=True)

st.title("🔬 PharmaSignal")
st.caption("Pharmacovigilance Signal Detection & Follow-Up Prioritisation")

tab1, tab2, tab3 = st.tabs(["Signal Detection", "Follow-Up Priority", "About"])


# ── Helper functions ──────────────────────────────────────────────

def grade_badge_html(grade):
    """Return colored HTML badge for evidence grade."""
    css_class = {
        "Strong": "grade-strong",
        "Confirmed": "grade-confirmed",
        "Moderate": "grade-moderate",
        "Weak": "grade-weak",
        "Inconclusive": "grade-inconclusive",
    }.get(grade, "grade-inconclusive")
    return f'<span class="grade-badge {css_class}">{grade}</span>'


def priority_badge_html(tier):
    """Return colored HTML badge for priority tier."""
    css_class = {
        "CRITICAL": "priority-critical",
        "HIGH": "priority-high",
        "MEDIUM": "priority-medium",
        "LOW": "priority-low",
    }.get(tier, "priority-low")
    return f'<span class="{css_class}">{tier}</span>'


def get_recommended_action(grade, label_status, prr):
    """Return a specific recommended action based on signal characteristics."""
    if grade == "Confirmed":
        return ("routine", "Continue routine monitoring. Event is documented in the FDA label.")
    if grade == "Strong" and label_status == "novel":
        return ("urgent", f"Escalate for urgent review. Novel signal with Strong evidence and PRR {prr:.1f}.")
    if grade == "Strong" and label_status != "novel":
        return ("monitor", "Monitor for reporting rate changes. Known signal with strong statistical presence.")
    if grade == "Moderate" and label_status == "novel":
        return ("urgent", "Flag for PV team review. Novel signal with moderate evidence — gather additional case data.")
    if grade == "Moderate":
        return ("monitor", "Schedule periodic review. Moderate evidence warrants continued surveillance.")
    if grade in ["Weak", "Inconclusive"] and label_status == "novel" and prr > 10:
        return ("monitor", f"Add to watch list. High PRR ({prr:.1f}) but insufficient published evidence — request literature search.")
    if grade in ["Weak", "Inconclusive"]:
        return ("routine", "No immediate action. Mark for next periodic review cycle.")
    return ("routine", "Standard monitoring.")


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

    if retrospective and date_end:
        st.info(f"⏳ Retrospective mode: using only FAERS data and PubMed articles before {date_end[:4]}-{date_end[4:6]}-{date_end[6:8]}. Current drug labels are excluded from evidence grading.")

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

                    # Evidence synthesis
                    st.subheader("Evidence Reports")
                    with st.spinner("Fetching labels, PubMed, and running LLM synthesis..."):
                        from rag.synthesize_report import synthesize_all_signals
                        from data.fetch_label import fetch_label_sections

                        label = fetch_label_sections(drug_name)
                        reports = synthesize_all_signals(drug_name, flagged, label,
                                                        max_signals=max_signals,
                                                        date_end=date_end)

                        # Summary metrics
                        if reports:
                            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                            novel_count = sum(1 for r in reports if r.get("label_status") == "novel")
                            known_count = len(reports) - novel_count
                            strong_count = sum(1 for r in reports if r.get("evidence_grade") in ["Strong", "Confirmed"])
                            abstained_count = sum(1 for r in reports if r.get("evidence_grade") in ["Inconclusive", "Weak"])

                            col_m1.metric("Signals Analysed", len(reports))
                            col_m2.metric("Novel", novel_count)
                            col_m3.metric("Strong / Confirmed", strong_count)
                            col_m4.metric("Abstained", abstained_count)

                        for r in reports:
                            label_status = r.get("label_status", "unknown")
                            novel_tag = "🆕 NOVEL" if label_status == "novel" else "📋 Known"
                            grade = r.get("evidence_grade", "?")
                            prr_val = r.get("prr", 0)

                            with st.expander(f"{r.get('event', '?')} — {grade} | {novel_tag}"):
                                # Top metrics row
                                col_a, col_b, col_c = st.columns(3)
                                col_a.metric("PRR", f"{prr_val:.3f}" if isinstance(prr_val, float) else prr_val)
                                col_b.metric("Evidence Grade", grade)
                                col_c.metric("PubMed Hits", r.get("pubmed_count", 0))

                                # Confirmed badge
                                if grade == "Confirmed":
                                    st.success("✅ This event is documented in the FDA-approved drug label.")

                                # Grade adjustment notice
                                if r.get("grade_adjusted"):
                                    st.info(f"ℹ️ {r['grade_adjusted']}")

                                # Retrospective notice
                                if date_end and label_status == "novel":
                                    st.caption(f"📅 Retrospective: graded using only pre-{date_end[:4]} evidence")

                                # Report content
                                if r.get("mechanism"):
                                    st.write(f"**Mechanism:** {r['mechanism']}")
                                if r.get("clinical_significance"):
                                    st.write(f"**Significance:** {r['clinical_significance']}")
                                if r.get("recommendation"):
                                    st.write(f"**Recommendation:** {r['recommendation']}")

                                # Abstention warning
                                if r.get("abstention_reason"):
                                    st.warning(f"Abstained: {r['abstention_reason']}")

                                # Citations
                                if r.get("key_citations"):
                                    st.write("**Citations:**")
                                    for cite in r["key_citations"][:5]:
                                        st.write(f"- {cite}")

                                # Recommended action
                                action_type, action_text = get_recommended_action(
                                    grade, label_status, prr_val if isinstance(prr_val, (int, float)) else 0
                                )
                                action_css = {
                                    "urgent": "action-urgent",
                                    "monitor": "action-monitor",
                                    "routine": "action-routine"
                                }.get(action_type, "action-routine")
                                action_icon = {"urgent": "🔴", "monitor": "🟡", "routine": "🟢"}.get(action_type, "⚪")
                                st.markdown(
                                    f'<div class="action-box {action_css}">'
                                    f'{action_icon} <strong>Action:</strong> {action_text}</div>',
                                    unsafe_allow_html=True
                                )

                    # Store for Tab 2
                    st.session_state["flagged"] = flagged
                    st.session_state["reports"] = reports
                    st.session_state["drug"] = drug_name
                    st.session_state["date_end"] = date_end

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
        date_end_stored = st.session_state.get("date_end")

        # Header with drug info
        header_col1, header_col2, header_col3 = st.columns([2, 1, 1])
        with header_col1:
            st.subheader(f"Drug: {drug}")
        with header_col2:
            st.metric("Total Signals", len(flagged))
        with header_col3:
            st.metric("Evidence Reports", len(reports))

        if date_end_stored:
            st.caption(f"📅 Retrospective mode — cutoff: {date_end_stored}")

        try:
            from followup.score_priority import rank_followup_priorities, filter_top_priority

            # Build label gaps from reports
            label_gaps = [{"status": r.get("label_status", "unknown"),
                          "match_score": 0} for r in reports]

            priorities = rank_followup_priorities(
                flagged[:len(reports)], label_gaps, reports
            )
            filtered, stats = filter_top_priority(priorities, top_pct=0.5)

            # Volume reduction metrics
            st.markdown("---")
            vol_col1, vol_col2, vol_col3 = st.columns(3)
            vol_col1.metric("Prioritised for Follow-Up",
                           f"{stats.get('kept', 0)} signals")
            vol_col2.metric("Volume Reduction",
                           f"{stats.get('reduction_pct', 0)}%",
                           delta=f"-{stats.get('removed', 0)} signals filtered out")
            vol_col3.metric("Min Priority Score",
                           f"{stats.get('min_score_kept', 0):.1f}")

            st.markdown("---")

            if filtered:
                # Priority queue — each signal as a card
                st.subheader("Priority Queue")

                for i, p in enumerate(filtered, 1):
                    tier = p.get("priority_tier", "LOW")
                    event = p.get("event", "Unknown")
                    prr = p.get("prr", 0)
                    score = p.get("priority_score", 0)
                    label_status = p.get("label_status", "unknown")
                    evidence_grade = p.get("evidence_grade", "?")
                    is_serious = p.get("is_serious", False)

                    # Card border color based on tier
                    card_class = tier.lower()

                    st.markdown(
                        f'<div class="signal-card {card_class}">'
                        f'<strong>#{i}</strong> &nbsp; {priority_badge_html(tier)} &nbsp; '
                        f'<strong>{event}</strong> &nbsp; '
                        f'{"🔴 Serious" if is_serious else ""}'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                    # Details columns
                    d_col1, d_col2, d_col3, d_col4, d_col5 = st.columns(5)
                    d_col1.metric("Priority Score", f"{score:.1f}")
                    d_col2.metric("PRR", f"{prr:.1f}" if isinstance(prr, (int, float)) else prr)
                    d_col3.metric("Evidence", evidence_grade)
                    d_col4.metric("Label Status", label_status.title())
                    d_col5.metric("Reports", p.get("count", "—"))

                    # Components breakdown
                    components = p.get("components", {})
                    if components:
                        with st.expander("Score breakdown"):
                            comp_cols = st.columns(5)
                            comp_cols[0].write(f"**Statistical:** {components.get('statistical', 0):.1f}")
                            comp_cols[1].write(f"**Severity:** {components.get('severity', 0):.1f}")
                            comp_cols[2].write(f"**Novelty:** {components.get('novelty', 0):.1f}")
                            comp_cols[3].write(f"**Evidence Gap:** {components.get('evidence_gap', 0):.1f}")
                            comp_cols[4].write(f"**Actionable:** {components.get('actionable_bonus', 0):.1f}")

                    # Recommended action
                    action_type, action_text = get_recommended_action(
                        evidence_grade, label_status,
                        prr if isinstance(prr, (int, float)) else 0
                    )
                    action_css = {
                        "urgent": "action-urgent",
                        "monitor": "action-monitor",
                        "routine": "action-routine"
                    }.get(action_type, "action-routine")
                    action_icon = {"urgent": "🔴", "monitor": "🟡", "routine": "🟢"}.get(action_type, "⚪")
                    st.markdown(
                        f'<div class="action-box {action_css}">'
                        f'{action_icon} <strong>Recommended:</strong> {action_text}</div>',
                        unsafe_allow_html=True
                    )

                    st.markdown("")  # spacing

                # Generate messages section
                st.markdown("---")
                st.subheader("Draft Follow-Up Communications")
                st.caption("Auto-generated message drafts for high-priority signals. Review before sending.")

                if st.button("Generate Follow-Up Messages", type="primary"):
                    with st.spinner("Generating professional follow-up drafts..."):
                        from followup.generate_message import generate_batch_messages
                        messages = generate_batch_messages(filtered, max_messages=3)

                        for msg in messages:
                            urgency = msg.get("urgency", "routine").upper()
                            urgency_icon = {"URGENT": "🔴", "PRIORITY": "🟠", "ROUTINE": "🟢"}.get(urgency, "⚪")

                            with st.expander(f"{urgency_icon} [{urgency}] {msg.get('event', '?')}"):
                                st.write(f"**To:** Healthcare Professional / Site Investigator")
                                st.write(f"**Subject:** {msg.get('subject', 'N/A')}")
                                st.markdown("---")
                                st.write(msg.get("body", ""))
                                st.markdown("---")
                                st.caption("⚠️ Draft only — requires human review before sending")

            else:
                st.info("No signals met the priority threshold for follow-up.")

        except Exception as e:
            st.error(f"Error: {e}")
            import traceback
            st.code(traceback.format_exc())


# ── Tab 3: About ─────────────────────────────────────────────────

with tab3:
    st.header("About PharmaSignal")

    st.markdown("""
    ### What This Does

    PharmaSignal is an agentic RAG system for pharmacovigilance signal detection.
    It takes a drug name and:

    1. **Queries FDA FAERS** — 20M+ adverse event reports from the real world
    2. **Computes disproportionality** — PRR, ROR, chi-squared to find statistical signals
    3. **Checks drug labels** — is this signal already documented (Known) or undocumented (Novel)?
    4. **Searches PubMed** — published case reports and studies for corroboration
    5. **LLM synthesis** — generates evidence-graded reports with mechanism and citations
    6. **Prioritises follow-up** — ranks signals by urgency for pharmacovigilance teams

    ### Evidence Grades

    | Grade | Meaning |
    |-------|---------|
    | **Confirmed** | Event is already documented in FDA-approved drug label |
    | **Strong** | Multiple studies/case reports with established mechanism |
    | **Moderate** | Some published evidence, plausible mechanism |
    | **Weak** | Limited evidence, mechanism unclear |
    | **Inconclusive** | Insufficient evidence to assess — system abstains |

    ### Retrospective Mode

    Tick "Retrospective mode" and enter a cutoff date to simulate early warning detection.
    The system uses only FAERS data and PubMed articles from before that date,
    and excludes current drug label information from evidence grading.
    This proves the system could have detected safety signals before the FDA acted.

    ### Evaluation Results

    | Tier | Metric | Result |
    |------|--------|--------|
    | Tier 1 | Signal Recall (12 drugs) | 8/12 (67%) |
    | Tier 2 | Serious False Positives | 0/4 (perfect) |
    | Tier 3 | RAG Grading Accuracy | 8/12 (67%) |
    | Tier 3 | Citation Groundedness | 11/12 (92%) |
    | Tier 4 | Data Leakage | 0 (perfect) |

    ### Data Sources

    - **openFDA FAERS API** — 20M+ adverse event reports
    - **DailyMed** — FDA-approved drug labels (SPL XML)
    - **PubMed E-utilities** — 35M+ biomedical abstracts

    ### Tech Stack

    Python · Groq (LLaMA 3.1) · ChromaDB · sentence-transformers ·
    LangChain · LangGraph · Streamlit
    """)
