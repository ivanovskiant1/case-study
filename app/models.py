"""Pydantic data shapes for the brief and the final recommendation."""
from typing import Literal, Optional
from pydantic import BaseModel, Field

Vertical = Literal["Retail", "Finance", "Travel", "QSR", "Entertainment"]
Geo = Literal["US", "EMEA", "APAC"]
Kpi = Literal["ctr", "ivr"]


class ClientBrief(BaseModel):
    advertiser: Optional[str] = None
    vertical: Optional[Vertical] = None
    kpi: Optional[Kpi] = None
    geo: Optional[Geo] = None
    budget_usd: Optional[float] = None
    impression_goal: Optional[int] = Field(
        default=None,
        description="Optional minimum impression goal stated by the client.",
    )

    def missing_required(self) -> list[str]:
        required = ["vertical", "kpi", "geo", "budget_usd"]
        return [f for f in required if getattr(self, f) is None]


class ProductOption(BaseModel):
    product_id: str
    product_name: str
    cpm: float
    estimated_impressions: int
    benchmark_ctr: float
    benchmark_ivr: float
    available_impressions: int
    inventory_risk: float
    risk_adjusted_impressions: int
    meets_scale: bool
    meets_impression_goal: bool
    notes: list[str] = []


class NoFitDiagnostic(BaseModel):
    """Concrete suggestions when no product fully fits the brief constraints."""

    max_budget_for_top_kpi: Optional[float] = Field(
        default=None,
        description="Budget at which the top-KPI product would fully fit on scale.",
    )
    top_kpi_product_name: Optional[str] = None
    alternative_geos: list[str] = Field(
        default_factory=list,
        description="Geos where the top-KPI product would fit at the current budget.",
    )
    achievable_impressions: Optional[int] = Field(
        default=None,
        description=(
            "When a product fits on scale but the impression goal is too high, "
            "this is the largest deliverable estimate."
        ),
    )
    achievable_product_name: Optional[str] = None


class Recommendation(BaseModel):
    brief: ClientBrief
    recommended: list[ProductOption]
    rejected: list[ProductOption] = []
    rationale: str
    no_fit_diagnostic: Optional[NoFitDiagnostic] = None
