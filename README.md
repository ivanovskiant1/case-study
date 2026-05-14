# Kargo Media Recommender

A chatbot-style assistant for Kargo media strategists. Paste a client brief; the assistant parses it, asks for any missing details, and recommends a product (with rejected alternatives, rationale, and concrete what-if suggestions when nothing fits) using historical campaign benchmarks and inventory forecasts.

---

## 🚀 Try it now — no setup required

**Live demo: https://k-case-study.streamlit.app**

The app is public — open the link in any browser and start typing briefs. No clone, no install, no API key needed on your side.

> **Note for reviewers:** Streamlit Community Cloud puts apps to sleep after ~7 days of no traffic. The first visit after a long idle takes ~30 seconds to wake up — just give it a moment.

### Three briefs to try

1. *"Acme Shoes is a Retail advertiser running in the US with a $30,000 budget. They care most about click-through rate."*
   → complete brief, one-shot recommendation
2. *"A new mobile app wants efficient awareness in the US with a $25,000 budget and strong in-view performance."*
   → assistant will ask for the vertical, then recommend
3. *"CineVerse is an Entertainment advertiser running in EMEA with a $40,000 budget. They care most about click-through rate."*
   → no product fully fits; assistant proposes concrete budget/geo adjustments

---

## Stack

- **LLM:** Anthropic Claude (Sonnet 4.6) via the official `anthropic` Python SDK — native tool-use loop, no agent framework
- **UI:** Streamlit chat with a structured recommendation card
- **Data:** three CSVs loaded into pandas in memory
- **Validation:** Pydantic models for the brief and the recommendation payload

**Core design decision:** the LLM is responsible for parsing, clarifying, and a 1-line intro. All ranking math (benchmarks, impression estimates, inventory checks, no-fit diagnostics) is deterministic Python — the model never invents numbers.

---

## Project layout

```
app/
  data.py        # CSV loading
  models.py      # Pydantic: ClientBrief, ProductOption, Recommendation, NoFitDiagnostic
  tools.py       # Deterministic recommendation pipeline + no-fit diagnostics
  agent.py       # Claude tool-use loop, holds brief state
  app.py         # Streamlit UI + structured card renderer
streamlit_app.py # Entry point
eval.py          # Runs all 7 sample briefs through the agent and prints traces
requirements.txt
.env.example
```

---

## Running locally

You only need this if you want to modify the code. To use the app, just open the live URL above.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and put your Anthropic API key in it

streamlit run streamlit_app.py
```

Open the URL Streamlit prints (typically `http://localhost:8501`).

To run the eval harness against all 7 sample briefs:

```bash
python eval.py
```

---

## How it works

1. **State lives in `MediaAgent.brief`**, not in the LLM. Each turn, the current state is appended to the system prompt so the model knows which slots are filled.
2. **Three tools** exposed to the model:
   - `reset_brief()` — clears state when a new client/brief is described, so prior fields don't leak across briefs.
   - `set_brief_fields(...)` — incrementally fills slots from the user's message.
   - `generate_recommendation()` — runs the deterministic pipeline once all required slots are present.
3. **Recommendation pipeline** (`app/tools.py:build_recommendation`):
   - Aggregate `campaign_history.csv` by `(product_id, vertical)` → CTR and in-view rate benchmarks.
   - Estimate impressions = `budget / cpm × 1000`.
   - Look up `inventory_forecaster.csv` for `(product_id, vertical, geo)`.
   - Discount available impressions by `inventory_risk` to get risk-adjusted capacity.
   - Filter products that meet scale and any stated impression goal; rank survivors by the requested KPI.
   - Acknowledge any higher-KPI rejected alternative in the rationale, with the specific blocking reason.
4. **No-fit diagnostics** kick in when nothing fully fits:
   - Largest budget at which the top-KPI product would fit on scale.
   - Alternative geos where the top-KPI product would fit at the current budget.
   - Largest deliverable impression count if scale fits but the impression goal doesn't.

---

## Handling `inventory_risk`

`inventory_risk` is a 0–1 forecast confidence score. We treat it as a multiplier: `risk_adjusted = available_imps × inventory_risk`. A product whose estimated impressions exceed the risk-adjusted figure is flagged as not meeting scale, even if raw `available_imps` is enough. Products with `inventory_risk < 0.80` get an additional warning note in the response.

**Why a multiplier:** a 1.5M-impression forecast at 70% confidence isn't worth the same as one at 95%. Multiplying captures this monotonically with one transparent line of math.

---

## What is intentionally minimal

- No persistence — each session starts fresh.
- No streaming — one response per turn for clarity.
- Single-product recommendation — bundles could be added by extending the ranker.
- One geo / vertical per brief — multi-market campaigns would need extension.
- Eval is observational, not asserted — `eval.py` prints traces; a CI-grade harness would `assert` expected outputs.
