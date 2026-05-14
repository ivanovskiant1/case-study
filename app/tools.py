"""Deterministic product recommendation logic. The LLM does not do math here."""
from typing import Optional
import pandas as pd

from . import data
from .models import ClientBrief, NoFitDiagnostic, ProductOption, Recommendation


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


def _diagnose_no_fit(
    options: list[ProductOption], brief: ClientBrief, kpi_field: str
) -> NoFitDiagnostic:
    """Compute concrete what-if suggestions when nothing fully fits."""
    diag = NoFitDiagnostic()
    if not options:
        return diag

    # The product the strategist would most want — highest KPI, regardless of fit.
    top = max(options, key=lambda o: getattr(o, kpi_field))
    diag.top_kpi_product_name = top.product_name

    # 1) Budget reduction — largest budget at which the top-KPI product
    # would fully fit on scale (risk-adjusted).
    diag.max_budget_for_top_kpi = round(
        top.risk_adjusted_impressions * top.cpm / 1000, -2
    )

    # 2) Geo switch — would the top-KPI product fit at the current budget
    # in any *other* geo for the same vertical?
    other_geos = [g for g in ("US", "EMEA", "APAC") if g != brief.geo]
    for g in other_geos:
        inv = lookup_inventory(top.product_id, brief.vertical, g)
        if not inv:
            continue
        risk_adj = int(inv["available_imps"] * inv["inventory_risk"])
        if top.estimated_impressions <= risk_adj:
            diag.alternative_geos.append(g)

    # 3) Achievable impressions — when a product fits scale but falls short
    # of the impression goal, report the largest deliverable estimate.
    if brief.impression_goal is not None:
        scale_ok = [o for o in options if o.meets_scale]
        if scale_ok:
            best = max(scale_ok, key=lambda o: o.estimated_impressions)
            diag.achievable_impressions = best.estimated_impressions
            diag.achievable_product_name = best.product_name

    return diag


def _format_no_fit_rationale(diag: NoFitDiagnostic, brief: ClientBrief) -> str:
    parts = [
        f"No product fully fits a ${brief.budget_usd:,.0f} buy in "
        f"{brief.geo} {brief.vertical}."
    ]
    if diag.max_budget_for_top_kpi and diag.max_budget_for_top_kpi < brief.budget_usd:
        parts.append(
            f"To fully deliver {diag.top_kpi_product_name} (top {brief.kpi.upper()}), "
            f"reduce the buy to ~${diag.max_budget_for_top_kpi:,.0f}."
        )
    if diag.alternative_geos:
        parts.append(
            f"{diag.top_kpi_product_name} would fit at the current budget in "
            f"{', '.join(diag.alternative_geos)}."
        )
    if diag.achievable_impressions and diag.achievable_product_name:
        parts.append(
            f"At this budget, {diag.achievable_product_name} can deliver "
            f"~{diag.achievable_impressions:,} impressions "
            f"(below the {brief.impression_goal:,} goal)."
        )
    return " ".join(parts)


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
        # If any non-viable product has a higher KPI than the winner, surface
        # the top one in the rationale so the tradeoff is explicit.
        higher_kpi_rejected = sorted(
            [
                o
                for o in options
                if o not in viable
                and getattr(o, kpi_field) > getattr(winner, kpi_field)
            ],
            key=lambda o: getattr(o, kpi_field),
            reverse=True,
        )
        if higher_kpi_rejected:
            alt = higher_kpi_rejected[0]
            alt_kpi = getattr(alt, kpi_field)
            if not alt.meets_scale:
                reason = (
                    f"its risk-adjusted inventory ({alt.risk_adjusted_impressions:,}) "
                    f"can't cover the {alt.estimated_impressions:,} impressions "
                    f"needed at this budget"
                )
            else:
                reason = (
                    f"its estimated impressions ({alt.estimated_impressions:,}) "
                    f"fall short of the client's {brief.impression_goal:,} goal"
                )
            rationale += (
                f" {alt.product_name} has a higher {brief.kpi.upper()} "
                f"({alt_kpi:.4f}) but {reason}."
            )
        recommended = viable[:1]
        no_fit_diagnostic = None
    else:
        # Nothing fits cleanly. Surface the best-by-KPI as a tradeoff candidate,
        # plus concrete what-if suggestions the strategist can act on.
        options.sort(key=lambda o: getattr(o, kpi_field), reverse=True)
        recommended = options[:1]
        no_fit_diagnostic = _diagnose_no_fit(options, brief, kpi_field)
        rationale = _format_no_fit_rationale(no_fit_diagnostic, brief)

    recommended_ids = {o.product_id for o in recommended}
    rejected = [o for o in options if o.product_id not in recommended_ids]
    rejected.sort(key=lambda o: getattr(o, kpi_field), reverse=True)

    return Recommendation(
        brief=brief,
        recommended=recommended,
        rejected=rejected[:3],
        rationale=rationale,
        no_fit_diagnostic=no_fit_diagnostic,
    )
