"""CSV loading. Loaded once at import time."""
from pathlib import Path
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent

products = pd.read_csv(DATA_DIR / "product_catalog.csv")
campaigns = pd.read_csv(DATA_DIR / "campaign_history.csv")
inventory = pd.read_csv(DATA_DIR / "inventory_forecaster.csv")

VERTICALS = ["Retail", "Finance", "Travel", "QSR", "Entertainment"]
GEOS = ["US", "EMEA", "APAC"]
KPIS = ["ctr", "ivr"]
