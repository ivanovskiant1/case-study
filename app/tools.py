"""Deterministic product recommendation logic. The LLM does not do math here."""
from typing import Optional
import pandas as pd

from . import data
from .models import ClientBrief, ProductOption, Recommendation


def get_benchmarks(vertical: str) -> pd.DataFrame:
    """CTR and in-view rate per product, computed from campaign history for one vertical."""
    rows = data.campaigns[data.campaigns["vertical"] == vertical]
    agg = rows.groupby("product_id").agg(
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
        viewable=("viewable_impressions", "sum"),
    )
    agg["ctr"] = agg["clicks"] / agg["impressions"]
    agg["ivr"] = agg["viewable"] / agg["impressions"]
    return agg[["ctr", "ivr"]]


def estimate_impressions(budget_usd: float, cpm: float) -> int:
    """Impressions = (budget / CPM) * 1000."""
    return int((budget_usd / cpm) * 1000)


def lookup_inventory(product_id: str, vertical: str, geo: str) -> Optional[dict]:
    row = data.inventory[
        (data.inventory["product_id"] == product_id)
        & (data.inventory["vertical"] == vertical)
        & (data.inventory["geo"] == geo)
    ]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "available_imps": int(r["available_imps"]),
        "inventory_risk": float(r["inventory_risk"]),
    }


def build_recommendation(brief: ClientBrief) -> Recommendation:
    """Full recommendation pipeline: benchmarks -> impressions -> inventory -> rank."""
    assert brief.vertical and brief.kpi and brief.geo and brief.budget_usd, (
        "Brief must be complete before calling build_recommendation"
    )
    benchmarks = get_benchmarks(brief.vertical)
    options: list[ProductOption] = []

    for _, p in data.products.iterrows():
        pid = p["product_id"]
        est_imps = estimate_impressions(brief.budget_usd, p["cpm"])
        inv = lookup_inventory(pid, brief.vertical, brief.geo)
        bench = benchmarks.loc[pid] if pid in benchmarks.index else None

        if inv is None or bench is None:
            continue

        # inventory_risk is treated as forecast confidence; we discount available
        # impressions by it so a low-confidence forecast can't be trusted at face value.
        risk_adj = int(inv["available_imps"] * inv["inventory_risk"])
        meets_scale = est_imps <= risk_adj
        meets_goal = (
            brief.impression_goal is None or est_imps >= brief.impression_goal
        )

        notes: list[str] = []
        if not meets_scale:
            notes.append(
                f"Risk-adjusted inventory ({risk_adj:,}) below estimated impressions ({est_imps:,})."
            )
        if not meets_goal:
            notes.append(
                f"Estimated impressions ({est_imps:,}) below the client's goal ({brief.impression_goal:,})."
            )
        if inv["inventory_risk"] < 0.80:
            notes.append(
                f"Inventory forecast confidence is low ({inv['inventory_risk']:.2f})."
            )

        options.append(
            ProductOption(
                product_id=pid,
                product_name=p["product_name"],
                cpm=float(p["cpm"]),
                estimated_impressions=est_imps,
                benchmark_ctr=float(bench["ctr"]),
                benchmark_ivr=float(bench["ivr"]),
                available_impressions=int(inv["available_imps"]),
                inventory_risk=float(inv["inventory_risk"]),
                risk_adjusted_impressions=risk_adj,
                meets_scale=meets_scale,
                meets_impression_goal=meets_goal,
                notes=notes,
            )
        )

    kpi_field = "benchmark_ctr" if brief.kpi == "ctr" else "benchmark_ivr"
    viable = [o for o in options if o.meets_scale and o.meets_impression_goal]
    viable.sort(key=lambda o: getattr(o, kpi_field), reverse=True)

    if viable:
        winner = viable[0]
        rationale = (
            f"{winner.product_name} has the highest {brief.kpi.upper()} benchmark "
            f"({getattr(winner, kpi_field):.4f}) among products that fit the "
            f"{brief.geo} {brief.vertical} inventory and budget."
        )
        recommended = viable[:1]
    else:
        # Nothing fits cleanly. Surface the best-by-KPI as a tradeoff candidate.
        options.sort(key=lambda o: getattr(o, kpi_field), reverse=True)
        recommended = options[:1]
        rationale = (
            "No product fully meets the scale/impression-goal constraints. "
            "Best-by-KPI shown with tradeoffs noted."
        )

    recommended_ids = {o.product_id for o in recommended}
    rejected = [o for o in options if o.product_id not in recommended_ids]
    rejected.sort(key=lambda o: getattr(o, kpi_field), reverse=True)

    return Recommendation(
        brief=brief,
        recommended=recommended,
        rejected=rejected[:3],
        rationale=rationale,
    )
