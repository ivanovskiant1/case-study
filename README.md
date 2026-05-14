# Kargo Media Recommender

A chatbot-style assistant for Kargo media strategists. Paste a client brief; the assistant parses it, asks for any missing details, and recommends a product (with a small rejected-alternatives list and rationale) using historical campaign benchmarks and inventory forecasts.

## Stack

- **LLM**: Anthropic Claude (Sonnet) via the official `anthropic` Python SDK — native tool-use loop, no agent framework
- **UI**: Streamlit chat
- **Data**: three CSVs loaded into pandas in memory
- **Validation**: Pydantic models for the brief and the recommendation payload

Design decision: the LLM is responsible for parsing, clarifying, and explaining. All ranking math (benchmarks, impression estimates, inventory checks) is deterministic Python — the model never invents numbers.

## Project layout

```
app/
  data.py        # CSV loading
  models.py      # Pydantic: ClientBrief, ProductOption, Recommendation
  tools.py       # deterministic recommendation pipeline
  agent.py       # Claude tool-use loop, holds brief state
  app.py         # Streamlit UI
streamlit_app.py # entry point
requirements.txt
.env.example
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and put your Anthropic API key in it
```

## Run

```bash
streamlit run streamlit_app.py
```

Open the URL Streamlit prints (typically `http://localhost:8501`).

## Try it

Sample briefs from `client_briefs.json`:

- *"Acme Shoes is a Retail advertiser running in the US with a $30,000 budget. They care most about click-through rate."*
- *"A new mobile app wants efficient awareness in the US with a $25,000 budget"* — assistant will ask for vertical.
- *"A Finance brand wants a recommendation for EMEA with a $25,000 budget"* — assistant will ask which KPI matters.

## How it works

1. **State** lives in `MediaAgent.brief` (a `ClientBrief`), not in the LLM. Each turn, the current state is appended to the system prompt so the model knows which slots are filled.
2. **Two tools** exposed to the model:
   - `set_brief_fields(...)` — incrementally fill slots from the user's message.
   - `generate_recommendation()` — runs the deterministic pipeline once required slots are present.
3. **Recommendation pipeline** (`app/tools.py:build_recommendation`):
   - Aggregate `campaign_history.csv` by `(product_id, vertical)` → CTR and in-view rate benchmarks.
   - Estimate impressions = `budget / cpm * 1000`.
   - Look up `inventory_forecaster.csv` for `(product_id, vertical, geo)`.
   - Discount available impressions by `inventory_risk` (treating it as forecast confidence) to get risk-adjusted capacity.
   - Filter products that meet scale and any stated impression goal; rank survivors by the requested KPI.
   - If nothing fits, return the best-by-KPI as a tradeoff candidate with notes explaining why constraints were violated.

## Handling `inventory_risk`

`inventory_risk` is a 0–1 forecast confidence score. We treat it as a multiplier: `risk_adjusted = available_imps * inventory_risk`. A product whose estimated impressions exceeds the risk-adjusted figure is flagged as not meeting scale, even if raw `available_imps` is enough. Products with `inventory_risk < 0.80` get an additional warning note.

## What is intentionally minimal

- No persistence; each session starts fresh.
- No streaming; one response per turn for clarity.
- The recommendation always returns the single top product. Bundles (two complementary products) could be added by extending the ranker.
