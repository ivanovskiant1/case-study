"""Streamlit chat UI. Call `render()` from the entry point on each rerun."""
import streamlit as st

from app.agent import MediaAgent
from app.models import Recommendation

WELCOME_MESSAGE = """Hi — I'm your **Kargo media-strategy assistant**. Paste a client brief and I'll recommend a product (with benchmarks, inventory checks, and rejected alternatives).

For a **one-shot recommendation with no follow-ups**, include all of these:

- **Vertical** — Retail, Finance, Travel, QSR, or Entertainment
- **Geo** — US, EMEA, or APAC
- **Primary KPI** — click-through rate or in-view rate
- **Budget** — in USD
- *(optional)* Advertiser name and a minimum impression goal

**Example:**
> *Acme Shoes is a Retail advertiser running in the US with a $30,000 budget. They care most about click-through rate.*

Missing something? Just give me what you have — I'll ask for the rest."""


def _render_recommendation_card(rec: Recommendation) -> None:
    """Native Streamlit components for the recommendation. No LLM-formatted Markdown."""
    if not rec.recommended:
        return
    top = rec.recommended[0]
    kpi = rec.brief.kpi
    kpi_label = "CTR" if kpi == "ctr" else "In-View Rate"
    kpi_value = top.benchmark_ctr if kpi == "ctr" else top.benchmark_ivr

    fits = top.meets_scale and top.meets_impression_goal
    badge = "✅ Recommended" if fits else "⚠️ Best available (with tradeoffs)"

    with st.container(border=True):
        st.markdown(f"### {badge}: {top.product_name}")
        st.caption(f"Product ID: `{top.product_id}` · CPM ${top.cpm:.2f}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Estimated impressions", f"{top.estimated_impressions:,}")
        c2.metric(f"Benchmark {kpi_label}", f"{kpi_value:.2%}")
        c3.metric(
            "Risk-adj. inventory",
            f"{top.risk_adjusted_impressions:,}",
            help=f"Available {top.available_impressions:,} × risk {top.inventory_risk:.2f}",
        )
        c4.metric("Inventory confidence", f"{top.inventory_risk:.2f}")

        st.markdown(f"**Rationale.** {rec.rationale}")

        for note in top.notes:
            st.warning(note, icon="⚠️")

    if rec.rejected:
        with st.expander(f"Rejected alternatives ({len(rec.rejected)})", expanded=False):
            for opt in rec.rejected:
                opt_kpi = opt.benchmark_ctr if kpi == "ctr" else opt.benchmark_ivr
                st.markdown(
                    f"**{opt.product_name}** — {kpi_label} {opt_kpi:.2%} · "
                    f"Est. {opt.estimated_impressions:,} imps · "
                    f"Risk-adj. avail. {opt.risk_adjusted_impressions:,}"
                )
                for note in opt.notes:
                    st.caption(f"↳ {note}")


def render() -> None:
    st.set_page_config(page_title="Kargo Media Recommender", layout="wide")
    st.title("Kargo Media Recommender")
    st.caption("Paste a client brief. I'll ask for anything missing and recommend a product.")

    if "agent" not in st.session_state:
        st.session_state.agent = MediaAgent()
        st.session_state.messages = [
            {"role": "assistant", "content": WELCOME_MESSAGE}
        ]

    agent: MediaAgent = st.session_state.agent

    prompt = st.chat_input("Type a client brief or answer a follow-up...")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        try:
            reply = agent.chat(prompt)
        except Exception as e:
            reply = f"**Error:** `{type(e).__name__}: {e}`"
        msg = {"role": "assistant", "content": reply}
        # Snapshot the recommendation onto the message so it survives reruns.
        if agent.latest_recommendation and agent.latest_recommendation.recommended:
            msg["recommendation"] = agent.latest_recommendation.model_copy(deep=True)
            agent.latest_recommendation = None  # consume so it only renders once
        st.session_state.messages.append(msg)
        st.rerun()

    with st.sidebar:
        st.subheader("Current brief")
        st.json(agent.brief.model_dump(exclude_none=True) or {"(empty)": ""})
        missing = agent.brief.missing_required()
        st.markdown(f"**Missing:** {', '.join(missing) if missing else '_none_'}")
        if st.button("Reset conversation"):
            st.session_state.clear()
            st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if "recommendation" in msg:
                _render_recommendation_card(msg["recommendation"])
