
# GHOTRA'S CAPITAL — ONE-CELL WEEKLY MACRO NEWSLETTER GENERATOR
# Run this entire cell every Monday morning.
# Saves everything automatically to:
# /Users/raj/Desktop/Investment Reports/Ghotra's Capital Python Scripts/Main FRED

# ----------------------------
# 0) Auto-install/import packages
# ----------------------------
import sys, subprocess, importlib.util

def ensure_package(import_name, pip_name=None):
    pip_name = pip_name or import_name
    if importlib.util.find_spec(import_name) is None:
        print(f"Installing {pip_name}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name, "--quiet"])

for import_name, pip_name in [
    ("pandas", "pandas"),
    ("requests", "requests"),
    ("matplotlib", "matplotlib"),
    ("numpy", "numpy"),
    ("dateutil", "python-dateutil"),
]:
    ensure_package(import_name, pip_name)

import html
import hashlib
import json
import math
import os
import random
import re
import textwrap
import time
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# ----------------------------
# 1) User settings
# ----------------------------
BRAND_TOP_LINE = "Ghotra’s Capital"
BRAND_SUB_LINE = "Weekly Macro Market Analysis"
BRAND_NAME = "Ghotra's Capital"
REPORT_TITLE_PREFIX = "Ghotra Macro Weekly"

# Fixed save path. No more folder prompt.
BASE_DIR = Path(r"/Users/raj/Desktop/Investment Reports/Ghotra's Capital Python Scripts/Main FRED")

# Optional FRED API key is not required because this notebook uses FRED CSV graph downloads.
FRED_API_KEY = os.getenv("FRED_API_KEY", "").strip()

# Report behavior
SKIP_GDELT = True           # Headline-link section removed from the public report by default.
CREATE_CHARTS = True        # Set False if you only want the text + CSV report.
OPEN_HTML_AFTER = True      # Opens report automatically after it is created.
LOOKBACK_DAYS = 420         # Enough data to chart trends and calculate weekly changes.
REQUEST_TIMEOUT = 25
GDELT_DELAY_SECONDS = 2.0   # Helps reduce GDELT 429 rate-limit errors.

# Wording variation / local AI rewrite settings.
# No API key is used. If Ollama is running locally, the notebook can ask a local model
# to polish sections. If Ollama is not installed/running, the built-in analyst
# variation engine still creates fresh professional wording every run.
USE_LOCAL_LLM_REWRITER = True
LOCAL_LLM_MODEL = os.getenv("GHOTRA_LOCAL_LLM_MODEL", "llama3.2")
LOCAL_LLM_URL = os.getenv("GHOTRA_LOCAL_LLM_URL", "http://localhost:11434/api/generate")
VARIATION_LOCK_TO_WEEK = False  # False = fresh wording on every run; True = same wording for the same release week.
RUN_VARIATION_ID = datetime.now().strftime("%Y%m%d%H%M%S")

# ----------------------------
# 2) Date + folder logic
# ----------------------------
def last_completed_friday(today: Optional[date] = None) -> date:
    """Returns the most recent Friday before today. Good for Monday morning reports."""
    today = today or date.today()
    days_since_friday = (today.weekday() - 4) % 7
    if days_since_friday == 0:
        days_since_friday = 7
    return today - timedelta(days=days_since_friday)

WEEK_END = last_completed_friday()
WEEK_START = WEEK_END - timedelta(days=4)
# Report is released the following Monday morning after the covered market week.
REPORT_RELEASE_DATE = WEEK_END + timedelta(days=3)
REPORT_DATE_STAMP = REPORT_RELEASE_DATE.strftime("%m.%d.%Y")

BASE_DIR.mkdir(parents=True, exist_ok=True)

def make_unique_folder(base_dir: Path, folder_name: str) -> Path:
    """Creates a dated folder and never overwrites an older run."""
    candidate = base_dir / folder_name
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=False)
        return candidate
    n = 2
    while True:
        candidate = base_dir / f"{folder_name}_v{n}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        n += 1

OUTPUT_DIR = make_unique_folder(BASE_DIR, f"Ghotra_Macro_Weekly_Released_{REPORT_DATE_STAMP}")
CHART_DIR = OUTPUT_DIR / "charts"
DATA_DIR = OUTPUT_DIR / "data"
CHART_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

print(f"Saving report to: {OUTPUT_DIR}")
print(f"Release date: {REPORT_RELEASE_DATE.strftime('%B %d, %Y')}")
print(f"Data coverage: {WEEK_START.strftime('%B %d, %Y')} to {WEEK_END.strftime('%B %d, %Y')}")

# ----------------------------
# 3) Series setup
# ----------------------------
@dataclass
class SeriesConfig:
    name: str
    series_ids: List[str]
    category: str
    unit: str
    higher_is: str
    why: str
    chart: bool = True
    pct_change: bool = False

SERIES: List[SeriesConfig] = [
    SeriesConfig(
        name="S&P 500",
        series_ids=["SP500"],
        category="Risk Appetite",
        unit="index",
        higher_is="risk-on",
        why="Shows whether investors were adding risk or pulling back from U.S. equities.",
        pct_change=True,
    ),
    SeriesConfig(
        name="VIX Volatility Index",
        series_ids=["VIXCLS"],
        category="Volatility",
        unit="index",
        higher_is="stress",
        why="Tracks the market’s fear premium. Higher VIX usually means traders are paying up for protection.",
        pct_change=False,
    ),
    SeriesConfig(
        name="10-Year Treasury Yield",
        series_ids=["DGS10"],
        category="Rates",
        unit="percent",
        higher_is="tighter financial conditions",
        why="A key discount-rate input for stocks, mortgages, credit, and valuation multiples.",
        pct_change=False,
    ),
    SeriesConfig(
        name="2-Year Treasury Yield",
        series_ids=["DGS2"],
        category="Rates",
        unit="percent",
        higher_is="hawkish Fed expectations",
        why="Often reflects what the market thinks the Fed will do over the near term.",
        pct_change=False,
    ),
    SeriesConfig(
        name="10Y–2Y Yield Curve",
        series_ids=["T10Y2Y"],
        category="Rates",
        unit="percentage points",
        higher_is="steeper curve",
        why="Helps show whether the bond market is pricing growth confidence or recession pressure.",
        pct_change=False,
    ),
    SeriesConfig(
        name="Effective Fed Funds Rate",
        series_ids=["DFF"],
        category="Fed Policy",
        unit="percent",
        higher_is="tighter policy",
        why="Shows the actual overnight policy rate banks are trading around.",
        pct_change=False,
    ),
    SeriesConfig(
        name="WTI Crude Oil",
        series_ids=["DCOILWTICO"],
        category="Energy",
        unit="dollars per barrel",
        higher_is="inflation pressure",
        why="Oil can influence inflation expectations, consumer costs, transport margins, and energy stocks.",
        pct_change=True,
    ),
    SeriesConfig(
        name="Gold",
        series_ids=["GOLDPMGBD228NLBM", "GOLDAMGBD228NLBM"],
        category="Safe Haven / Inflation Hedge",
        unit="dollars per troy ounce",
        higher_is="safe-haven/inflation bid",
        why="Gold can reflect real-rate pressure, dollar moves, inflation concern, or demand for safety.",
        pct_change=True,
    ),
    SeriesConfig(
        name="Broad U.S. Dollar Index",
        series_ids=["DTWEXBGS"],
        category="Dollar",
        unit="index",
        higher_is="stronger dollar",
        why="A stronger dollar can pressure commodities, foreign earnings translation, and global liquidity.",
        pct_change=True,
    ),
    SeriesConfig(
        name="High Yield Credit Spread",
        series_ids=["BAMLH0A0HYM2"],
        category="Credit",
        unit="percentage points",
        higher_is="credit stress",
        why="Wider junk-bond spreads can be an early sign that investors are demanding more risk compensation.",
        pct_change=False,
    ),
    SeriesConfig(
        name="Investment Grade Credit Spread",
        series_ids=["BAMLC0A0CM"],
        category="Credit",
        unit="percentage points",
        higher_is="credit stress",
        why="Tracks stress in higher-quality corporate credit markets.",
        pct_change=False,
    ),
    SeriesConfig(
        name="Fed Balance Sheet",
        series_ids=["WALCL"],
        category="Liquidity",
        unit="millions of dollars",
        higher_is="more liquidity",
        why="A liquidity backdrop measure. Shrinking liquidity can quietly tighten financial conditions.",
        pct_change=True,
    ),
    SeriesConfig(
        name="30-Year Mortgage Rate",
        series_ids=["MORTGAGE30US"],
        category="Housing",
        unit="percent",
        higher_is="housing pressure",
        why="Higher mortgage rates can weigh on housing affordability, builders, banks, and consumer confidence.",
        pct_change=False,
    ),
    SeriesConfig(
        name="Initial Jobless Claims",
        series_ids=["ICSA"],
        category="Labor Market",
        unit="claims",
        higher_is="labor weakness",
        why="A weekly read on labor-market softening. Rising claims can shift growth and Fed expectations.",
        pct_change=True,
    ),
]

# ----------------------------
# 4) Data functions
# ----------------------------
def safe_slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_")
    return text[:80] or "file"

def fred_csv_url(series_id: str, start: date, end: date) -> str:
    return (
        "https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?id={series_id}&cosd={start.isoformat()}&coed={end.isoformat()}"
    )

def fetch_one_fred_series(series_id: str, start: date, end: date) -> pd.DataFrame:
    """Fetch one FRED series. Returns empty DataFrame silently if unavailable."""
    url = fred_csv_url(series_id, start, end)
    headers = {"User-Agent": f"{BRAND_NAME.replace(' ', '-')}/1.0"}
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200 or not r.text.strip():
            return pd.DataFrame(columns=["date", "value"])
        from io import StringIO
        df = pd.read_csv(StringIO(r.text))
        if df.empty:
            return pd.DataFrame(columns=["date", "value"])
        date_col = "observation_date" if "observation_date" in df.columns else df.columns[0]
        value_col = series_id if series_id in df.columns else df.columns[-1]
        out = pd.DataFrame({
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "value": pd.to_numeric(df[value_col].replace(".", np.nan), errors="coerce"),
        })
        out = out.dropna(subset=["date", "value"]).sort_values("date").reset_index(drop=True)
        return out
    except Exception:
        return pd.DataFrame(columns=["date", "value"])

def fetch_series_with_fallback(cfg: SeriesConfig, start: date, end: date) -> Tuple[str, pd.DataFrame]:
    """Try the primary series ID, then fallbacks. Silent if all fail."""
    for sid in cfg.series_ids:
        df = fetch_one_fred_series(sid, start, end)
        if not df.empty:
            return sid, df
    return cfg.series_ids[0], pd.DataFrame(columns=["date", "value"])

def fetch_all_fred_data(start: date, end: date) -> Tuple[Dict[str, pd.DataFrame], Dict[str, str]]:
    data: Dict[str, pd.DataFrame] = {}
    used_ids: Dict[str, str] = {}
    for cfg in SERIES:
        sid, df = fetch_series_with_fallback(cfg, start, end)
        if not df.empty:
            data[cfg.name] = df
            used_ids[cfg.name] = sid
        time.sleep(0.15)
    return data, used_ids

def nearest_value_on_or_before(df: pd.DataFrame, target: date) -> Optional[pd.Series]:
    if df.empty:
        return None
    target_ts = pd.Timestamp(target)
    sub = df[df["date"] <= target_ts]
    if sub.empty:
        return None
    return sub.iloc[-1]

def format_value(value: float, unit: str) -> str:
    if value is None or pd.isna(value):
        return ""
    if unit in ["percent", "percentage points"]:
        return f"{value:,.2f}%"
    if unit == "millions of dollars":
        return f"${value/1_000_000:,.2f}T"
    if unit in ["dollars per barrel", "dollars per troy ounce"]:
        return f"${value:,.2f}"
    if unit == "claims":
        return f"{value:,.0f}"
    return f"{value:,.2f}"

def change_text(latest: float, prior: float, unit: str, pct_change: bool) -> Tuple[float, str, str]:
    if pd.isna(latest) or pd.isna(prior):
        return np.nan, "", "flat"
    raw = latest - prior
    if pct_change and prior not in [0, None] and not pd.isna(prior):
        pct = raw / prior * 100
        direction = "up" if pct > 0 else "down" if pct < 0 else "flat"
        return pct, f"{pct:+.2f}%", direction
    if unit in ["percent", "percentage points"]:
        bps = raw * 100
        direction = "up" if bps > 0 else "down" if bps < 0 else "flat"
        return bps, f"{bps:+.0f} bps", direction
    direction = "up" if raw > 0 else "down" if raw < 0 else "flat"
    return raw, f"{raw:+,.2f}", direction

def build_dashboard(data: Dict[str, pd.DataFrame], used_ids: Dict[str, str], week_end: date) -> pd.DataFrame:
    rows = []
    prior_target = week_end - timedelta(days=7)
    for cfg in SERIES:
        df = data.get(cfg.name, pd.DataFrame())
        if df.empty:
            continue
        latest = nearest_value_on_or_before(df, week_end)
        prior = nearest_value_on_or_before(df, prior_target)
        if latest is None or prior is None:
            continue
        latest_val = float(latest["value"])
        prior_val = float(prior["value"])
        change_num, change_label, direction = change_text(latest_val, prior_val, cfg.unit, cfg.pct_change)
        rows.append({
            "Category": cfg.category,
            "Series": cfg.name,
            "FRED ID": used_ids.get(cfg.name, cfg.series_ids[0]),
            "Latest Date": pd.Timestamp(latest["date"]).date().isoformat(),
            "Latest": latest_val,
            "Latest Display": format_value(latest_val, cfg.unit),
            "Prior Date": pd.Timestamp(prior["date"]).date().isoformat(),
            "Prior": prior_val,
            "Weekly Change Numeric": change_num,
            "Weekly Change": change_label,
            "Direction": direction,
            "Higher Usually Means": cfg.higher_is,
            "Why It Matters": cfg.why,
        })
    return pd.DataFrame(rows)

# ----------------------------
# 5) Professional investment-analyst commentary + wording variation engine
# ----------------------------
def variation_rng(namespace: str) -> random.Random:
    """Date/run-based randomizer so sections do not read the exact same way each week."""
    salt = REPORT_DATE_STAMP if VARIATION_LOCK_TO_WEEK else f"{REPORT_DATE_STAMP}-{RUN_VARIATION_ID}-{time.time_ns()}"
    raw = f"{BRAND_NAME}|{salt}|{namespace}"
    seed = int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)

def pick_from(options: List[str], namespace: str) -> str:
    if not options:
        return ""
    return variation_rng(namespace).choice(options)

def ordered_pick(options: List[str], namespace: str, count: int) -> List[str]:
    rng = variation_rng(namespace)
    items = list(options)
    rng.shuffle(items)
    return items[:count]

def get_row(dashboard: pd.DataFrame, series: str) -> Optional[pd.Series]:
    if dashboard.empty:
        return None
    sub = dashboard[dashboard["Series"].eq(series)]
    if sub.empty:
        return None
    return sub.iloc[0]

def signed_direction_word(row: Optional[pd.Series]) -> str:
    if row is None:
        return "stable"
    d = row.get("Direction", "flat")
    return "higher" if d == "up" else "lower" if d == "down" else "stable"

def direction_phrase(row: Optional[pd.Series], up_text: str, down_text: str, flat_text: str = "was broadly unchanged") -> str:
    if row is None:
        return ""
    d = row.get("Direction", "flat")
    if d == "up":
        return up_text
    if d == "down":
        return down_text
    return flat_text

def score_macro_backdrop(dashboard: pd.DataFrame) -> Tuple[int, str]:
    """Simple market backdrop score from -5 risk-off to +5 risk-on."""
    score = 0
    sp = get_row(dashboard, "S&P 500")
    vix = get_row(dashboard, "VIX Volatility Index")
    ten = get_row(dashboard, "10-Year Treasury Yield")
    oil = get_row(dashboard, "WTI Crude Oil")
    dollar = get_row(dashboard, "Broad U.S. Dollar Index")
    hy = get_row(dashboard, "High Yield Credit Spread")
    claims = get_row(dashboard, "Initial Jobless Claims")

    if sp is not None:
        score += 2 if sp["Direction"] == "up" else -2 if sp["Direction"] == "down" else 0
    if vix is not None:
        score += -2 if vix["Direction"] == "up" else 2 if vix["Direction"] == "down" else 0
    if ten is not None:
        score += -1 if ten["Direction"] == "up" else 1 if ten["Direction"] == "down" else 0
    if dollar is not None:
        score += -1 if dollar["Direction"] == "up" else 1 if dollar["Direction"] == "down" else 0
    if hy is not None:
        score += -2 if hy["Direction"] == "up" else 2 if hy["Direction"] == "down" else 0
    if oil is not None:
        score += -1 if oil["Direction"] == "up" else 0
    if claims is not None:
        score += -1 if claims["Direction"] == "up" else 1 if claims["Direction"] == "down" else 0

    score = max(-5, min(5, score))
    if score >= 3:
        label = pick_from(["Constructive risk backdrop", "Risk backdrop remains constructive", "Constructive but confirmation still matters"], "label_pos")
    elif score >= 1:
        label = pick_from(["Moderately constructive", "Selective but supportive", "Cautiously constructive"], "label_mod_pos")
    elif score <= -3:
        label = pick_from(["Defensive macro backdrop", "Risk backdrop has turned defensive", "Macro conditions favor caution"], "label_neg")
    elif score <= -1:
        label = pick_from(["Cautious and selective", "Selective risk environment", "Caution remains appropriate"], "label_mod_neg")
    else:
        label = pick_from(["Balanced, data-dependent backdrop", "Mixed macro backdrop", "Neutral but highly data-dependent"], "label_neutral")
    return score, label

def numeric_tokens(text: str) -> List[str]:
    return re.findall(r"[$%+\-]?[0-9][0-9,]*(?:\.[0-9]+)?%?", text)

def rewrite_with_local_llm(text: str, section_name: str) -> str:
    """
    Optional local-AI polish using Ollama with no API key.
    If Ollama is not running, or if the model changes numbers, the original text is kept.
    """
    if not USE_LOCAL_LLM_REWRITER or not text or len(text) < 80:
        return text
    prompt = f"""
You are editing a weekly macro-market newsletter written by a licensed Series 65 / Series 7 style investment analyst.
Rewrite the section below so it sounds natural, professional, and concise.
Rules:
- Do not mention AI, automation, scripts, data fetching, or model usage.
- Do not change any numbers, dates, ticker symbols, percentages, or market facts.
- Do not add investment advice, guarantees, price targets, or performance promises.
- Keep the meaning the same, but vary sentence structure and wording.
- Use a calm analyst tone suitable for a client-facing weekly market note.
- Return only the rewritten section text.

SECTION: {section_name}
TEXT:
{text}
""".strip()
    try:
        payload = {
            "model": LOCAL_LLM_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.55, "top_p": 0.90, "num_predict": 650},
        }
        r = requests.post(LOCAL_LLM_URL, json=payload, timeout=35)
        if r.status_code != 200:
            return text
        out = (r.json().get("response") or "").strip()
        if not out:
            return text
        # Guardrail: reject local rewrite if it drops important numeric tokens.
        original_nums = set(numeric_tokens(text))
        rewritten_nums = set(numeric_tokens(out))
        if original_nums and not original_nums.issubset(rewritten_nums):
            return text
        if any(bad in out.lower() for bad in ["as an ai", "automation", "script", "model cannot", "i cannot"]):
            return text
        return out
    except Exception:
        return text

def maybe_ai_polish_list(items: List[str], section_name: str) -> List[str]:
    polished = []
    for i, item in enumerate(items, start=1):
        polished.append(rewrite_with_local_llm(item, f"{section_name} paragraph {i}"))
    return polished

def generate_human_commentary(dashboard: pd.DataFrame, week_start: date, week_end: date) -> Dict[str, object]:
    """Professional analyst commentary with rotating sentence structure and optional no-key local AI polish."""
    score, label = score_macro_backdrop(dashboard)
    sp = get_row(dashboard, "S&P 500")
    vix = get_row(dashboard, "VIX Volatility Index")
    ten = get_row(dashboard, "10-Year Treasury Yield")
    two = get_row(dashboard, "2-Year Treasury Yield")
    curve = get_row(dashboard, "10Y–2Y Yield Curve")
    oil = get_row(dashboard, "WTI Crude Oil")
    gold = get_row(dashboard, "Gold")
    dollar = get_row(dashboard, "Broad U.S. Dollar Index")
    hy = get_row(dashboard, "High Yield Credit Spread")
    ig = get_row(dashboard, "Investment Grade Credit Spread")
    claims = get_row(dashboard, "Initial Jobless Claims")
    mortgage = get_row(dashboard, "30-Year Mortgage Rate")

    rate_phrase = pick_from([
        direction_phrase(ten,
            "rates moved higher, which can raise the discount-rate pressure on equities and keep valuation discipline important",
            "rates moved lower, which can ease pressure on longer-duration assets and rate-sensitive sectors",
            "rates were broadly stable, leaving earnings quality and credit conditions as the more important confirmations"),
        direction_phrase(ten,
            "the Treasury market leaned tighter, making multiple expansion harder to justify without stronger earnings support",
            "the Treasury market eased, improving the relative setup for growth assets and housing-sensitive areas",
            "the Treasury market did not send a decisive signal, so equity leadership and credit spreads carry more weight"),
        direction_phrase(ten,
            "yield pressure remained a key constraint for risk assets",
            "the decline in yields reduced one of the major headwinds for equities",
            "yield movement was limited enough that the broader risk tone mattered more than the rate tape alone"),
    ], "rate_phrase")

    vix_phrase = pick_from([
        direction_phrase(vix,
            "volatility firmed, showing that investors were paying more for protection",
            "volatility cooled, which is usually consistent with a cleaner risk-taking environment",
            "volatility stayed contained, suggesting the tape remained orderly"),
        direction_phrase(vix,
            "the VIX moved higher, which points to a less comfortable market backdrop",
            "the VIX moved lower, giving the equity market a more supportive volatility backdrop",
            "the VIX did not materially change the risk message"),
        direction_phrase(vix,
            "option markets priced more uncertainty into the close of the week",
            "option markets showed less stress by the end of the week",
            "option-market stress remained manageable"),
    ], "vix_phrase")

    credit_phrase = pick_from([
        direction_phrase(hy,
            "high-yield spreads widened, which deserves attention because credit often leads equity risk repricing",
            "high-yield spreads tightened, supporting the view that corporate-credit stress remains contained",
            "credit spreads were stable, offering no major warning from corporate credit"),
        direction_phrase(hy,
            "lower-quality credit softened, which argues for more selectivity",
            "lower-quality credit improved, helping confirm the risk-on message",
            "corporate credit did not materially weaken the broader market read"),
        direction_phrase(hy,
            "credit conditions became less forgiving",
            "credit conditions looked incrementally more supportive",
            "credit conditions looked broadly unchanged"),
    ], "credit_phrase")

    opening_templates = [
        f"The macro backdrop for the release week is best described as {label.lower()}. In practical portfolio terms, {rate_phrase}; {vix_phrase}; and {credit_phrase}.",
        f"The main takeaway is that the market should be judged by confirmation across rates, volatility, and credit—not by index price action alone. At this point, the backdrop screens as {label.lower()}: {rate_phrase}; {vix_phrase}; and {credit_phrase}.",
        f"This week’s investment read is {label.lower()}. The quality of the equity tape depends on whether {rate_phrase}, whether {vix_phrase}, and whether {credit_phrase}.",
    ]
    opening = [pick_from(opening_templates, "opening_1")]

    allocation_paragraphs = [
        "From an allocation perspective, a durable equity advance usually needs more than a higher index level. It is stronger when credit spreads are contained, volatility is declining or stable, and yields are not creating fresh valuation pressure.",
        "For portfolio positioning, the cleanest signal comes from cross-market confirmation. Equities can move first, but credit, volatility, the dollar, and yields help determine whether that move has institutional-quality support behind it.",
        "The bigger picture remains a confirmation exercise. If equities strengthen while credit stays calm and volatility remains contained, the advance has better quality. If those signals diverge, sector selection and risk control become more important.",
    ]
    opening.append(pick_from(allocation_paragraphs, "opening_2"))

    if sp is not None:
        sp_templates = [
            f"The S&P 500 finished the covered week at {sp['Latest Display']} with a weekly change of {sp['Weekly Change']}. That move is most useful when read alongside the Treasury market, credit spreads, crude oil, and the dollar.",
            f"The S&P 500 closed the covered period at {sp['Latest Display']}, changing {sp['Weekly Change']} for the week. The index move matters, but the better read is whether macro conditions are confirming or challenging that price action.",
            f"The equity benchmark ended the covered week at {sp['Latest Display']} after moving {sp['Weekly Change']}. For this report, the focus is not just direction; it is the quality of the move underneath the surface.",
        ]
        opening.append(pick_from(sp_templates, "opening_sp"))

    changed = []
    if ten is not None or two is not None or curve is not None:
        rate_bits = []
        if ten is not None:
            rate_bits.append(f"10-year Treasury at {ten['Latest Display']} ({ten['Weekly Change']})")
        if two is not None:
            rate_bits.append(f"2-year Treasury at {two['Latest Display']} ({two['Weekly Change']})")
        if curve is not None:
            rate_bits.append(f"10Y–2Y curve at {curve['Latest Display']} ({curve['Weekly Change']})")
        changed.append(pick_from([
            f"Rates remained one of the most important inputs for equity valuation. {'; '.join(rate_bits)}. The rate complex affects discount rates, bank profitability, housing affordability, and the relative appeal of cash versus equities.",
            f"The rates market continued to frame the equity setup. {'; '.join(rate_bits)}. This matters because higher yields can tighten financial conditions, while lower yields can improve the backdrop for longer-duration assets.",
            f"Treasury-market signals stayed central to the macro read. {'; '.join(rate_bits)}. The key question is whether yields are helping equity multiples or forcing investors to demand stronger earnings confirmation.",
        ], "changed_rates"))
    if oil is not None:
        changed.append(pick_from([
            f"WTI crude oil ended the week at {oil['Latest Display']} with a weekly move of {oil['Weekly Change']}. Oil remains important because sustained strength can feed inflation expectations and pressure margins, while sharp weakness can signal demand concerns.",
            f"Crude oil closed at {oil['Latest Display']}, changing {oil['Weekly Change']} for the week. Energy matters beyond the energy sector because it connects to inflation, transportation costs, consumer spending, and corporate margins.",
            f"The oil tape deserves attention after WTI finished at {oil['Latest Display']} ({oil['Weekly Change']}). A firm oil market can complicate the inflation story; a weaker oil market can point to softer demand conditions.",
        ], "changed_oil"))
    if gold is not None or dollar is not None:
        gold_txt = f"gold at {gold['Latest Display']} ({gold['Weekly Change']})" if gold is not None else "gold was not a primary signal"
        dollar_txt = f"the broad U.S. dollar index at {dollar['Latest Display']} ({dollar['Weekly Change']})" if dollar is not None else "the dollar was not a primary signal"
        changed.append(pick_from([
            f"Safe-haven and liquidity signals were evaluated through {gold_txt} and {dollar_txt}. The dollar matters for global liquidity and multinational earnings, while gold can reflect real-rate pressure, inflation hedging, or defensive demand.",
            f"The cross-asset liquidity read came through {gold_txt} and {dollar_txt}. A stronger dollar can tighten global conditions, while gold can act as a check on confidence in real rates and inflation expectations.",
            f"Gold and the dollar remain useful macro cross-checks, with {gold_txt} and {dollar_txt}. These signals help separate broad risk appetite from defensive positioning.",
        ], "changed_dollar_gold"))
    if hy is not None or ig is not None:
        hy_txt = f"high-yield spreads at {hy['Latest Display']} ({hy['Weekly Change']})" if hy is not None else "high-yield spreads unavailable"
        ig_txt = f"investment-grade spreads at {ig['Latest Display']} ({ig['Weekly Change']})" if ig is not None else "investment-grade spreads unavailable"
        changed.append(pick_from([
            f"Corporate credit remained one of the cleanest checks on equity risk appetite, with {hy_txt} and {ig_txt}. Stable or tighter spreads support the equity tape; widening spreads would argue for a more defensive stance.",
            f"Credit markets provided an important confirmation layer, with {hy_txt} and {ig_txt}. If spreads stay contained, the market can usually absorb volatility more easily; if they widen, equity rallies become lower quality.",
            f"The credit read matters because it reflects how investors are pricing default and liquidity risk. This week’s key credit levels were {hy_txt} and {ig_txt}.",
        ], "changed_credit"))
    if claims is not None:
        changed.append(pick_from([
            f"Initial jobless claims were {claims['Latest Display']} ({claims['Weekly Change']}). Labor-market data remains central because it connects consumer strength, recession risk, wage pressure, and Federal Reserve expectations.",
            f"Labor conditions were tracked through initial jobless claims at {claims['Latest Display']} ({claims['Weekly Change']}). The claims trend helps investors judge whether the economy is cooling gradually or deteriorating more quickly.",
            f"Initial claims came in at {claims['Latest Display']} with a weekly move of {claims['Weekly Change']}. This remains a useful early signal for household income, consumption, and the Fed’s policy path.",
        ], "changed_claims"))
    if mortgage is not None:
        changed.append(pick_from([
            f"The 30-year mortgage rate was {mortgage['Latest Display']} ({mortgage['Weekly Change']}). Housing, homebuilders, regional banks, and consumer confidence remain closely tied to the Treasury market.",
            f"Mortgage rates stayed relevant with the 30-year rate at {mortgage['Latest Display']} ({mortgage['Weekly Change']}). This keeps housing affordability and interest-rate-sensitive consumer behavior in focus.",
            f"Housing conditions remain linked to rates, with the 30-year mortgage rate at {mortgage['Latest Display']} ({mortgage['Weekly Change']}). That makes the housing channel an important indirect read on consumer pressure.",
        ], "changed_mortgage"))

    watch_pool = [
        "Watch whether Treasury yields confirm or challenge the equity move. A sustained rise in yields can pressure long-duration growth stocks and rate-sensitive sectors.",
        "Monitor credit spreads as a confirmation tool. Equity strength is more durable when high-yield and investment-grade spreads remain contained.",
        "Track oil and the dollar together. Oil affects inflation expectations and corporate margins, while the dollar influences global liquidity and multinational earnings translation.",
        "Use volatility as the risk-control signal. A falling or stable VIX supports risk appetite; a rising VIX alongside weaker credit would argue for more caution.",
        "Focus on market breadth beneath the S&P 500. If leadership is narrow, the index can look stronger than the average stock actually feels.",
        "Pay attention to mega-cap earnings revisions and forward guidance. Large index weights can move the S&P 500 even when smaller sectors are sending a different message.",
        "Watch financials for confirmation from the yield curve and credit quality. Banks often provide an early read on liquidity, lending standards, and economic confidence.",
        "Keep an eye on defensive sectors. Strength in healthcare, staples, or utilities can signal that investors are rotating toward stability instead of cyclical growth.",
    ]
    watchlist = ordered_pick(watch_pool, "watchlist", 4)

    next_watch_intro = pick_from([
        "The next week should be evaluated through the relationship between rates, credit, volatility, oil, and market leadership. The objective is to identify which signals confirm risk appetite and which signals challenge it.",
        "For the week ahead, the most important read is not one data point by itself. The better process is to compare the S&P 500 against rates, credit spreads, volatility, crude oil, the dollar, and leadership from the largest index weights.",
        "The next setup should be approached as a confirmation test. If equities, credit, and volatility point in the same direction, the message is cleaner. If they diverge, the market requires more selectivity.",
    ], "next_watch_intro")
    company_note = pick_from([
        "The company list below rotates weekly and is selected from major S&P 500 weights plus macro-sensitive sectors. The purpose is to watch leadership, not to create a buy list.",
        "These companies are useful market tells because they connect index leadership with the macro inputs that matter most: rates, credit, oil, consumer demand, and earnings quality.",
        "The names below help translate the macro backdrop into equity-market leadership. They are included as monitoring points for breadth, sector rotation, and risk appetite.",
    ], "company_note")

    opening = maybe_ai_polish_list(opening, "Big Picture Macro Read")
    changed = maybe_ai_polish_list(changed, "What Shifted Last Week")
    watchlist = maybe_ai_polish_list(watchlist, "What We Should Be Watching Next")
    next_watch_intro = rewrite_with_local_llm(next_watch_intro, "Next Week Intro")
    company_note = rewrite_with_local_llm(company_note, "Company Watchlist Note")

    return {
        "score": score,
        "label": label,
        "opening": opening,
        "changed": changed,
        "watchlist": watchlist,
        "next_watch_intro": next_watch_intro,
        "company_note": company_note,
        "variation_id": RUN_VARIATION_ID,
        "local_llm_attempted": bool(USE_LOCAL_LLM_REWRITER),
    }

# ----------------------------
# 6) Headline links — optional and clean
# ----------------------------
HEADLINE_TOPICS = {
    "Fed & Rates": 'Federal Reserve interest rates Treasury yields',
    "Inflation": 'inflation CPI PCE prices',
    "Oil & Energy": 'crude oil WTI OPEC energy prices',
    "Gold & Dollar": 'gold dollar Treasury yields safe haven',
    "Stocks & Volatility": 'S&P 500 stock market volatility VIX',
    "Credit & Banks": 'credit spreads banks lending financial conditions',
}

def fetch_gdelt_topic(topic: str, query: str, start: date, end: date, maxrecords: int = 4) -> pd.DataFrame:
    """Fetch headline links from GDELT. Silent on failure so the report stays clean."""
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": maxrecords,
        "sort": "datedesc",
        "startdatetime": start.strftime("%Y%m%d") + "000000",
        "enddatetime": end.strftime("%Y%m%d") + "235959",
    }
    headers = {"User-Agent": f"{BRAND_NAME.replace(' ', '-')}/1.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return pd.DataFrame(columns=["Topic", "Title", "Source", "URL", "Seen Date"])
        js = r.json()
        articles = js.get("articles", []) or []
        rows = []
        for a in articles[:maxrecords]:
            title = str(a.get("title", "")).strip()
            url = str(a.get("url", "")).strip()
            source = str(a.get("domain", "")).strip()
            seen = str(a.get("seendate", "")).strip()
            if title and url:
                rows.append({
                    "Topic": topic,
                    "Title": title,
                    "Source": source,
                    "URL": url,
                    "Seen Date": seen,
                })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=["Topic", "Title", "Source", "URL", "Seen Date"])

def fetch_macro_headlines(start: date, end: date) -> pd.DataFrame:
    frames = []
    for topic, query in HEADLINE_TOPICS.items():
        df = fetch_gdelt_topic(topic, query, start, end, maxrecords=4)
        if not df.empty:
            frames.append(df)
        time.sleep(GDELT_DELAY_SECONDS)
    if not frames:
        return pd.DataFrame(columns=["Topic", "Title", "Source", "URL", "Seen Date"])
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["URL"]).reset_index(drop=True)
    return out


# ----------------------------
# 6B) Rotating S&P 500 company watchlist for the next week
# ----------------------------
SP500_COMPANY_WATCHLIST = [
    {"Ticker": "AAPL", "Company": "Apple", "Sector / Lens": "Consumer hardware / services", "Bucket": "mega_cap_growth", "Why Watch": "Large S&P 500 weight; useful read-through for consumer demand, China exposure, services margins, and mega-cap risk appetite."},
    {"Ticker": "MSFT", "Company": "Microsoft", "Sector / Lens": "Software / cloud / AI", "Bucket": "mega_cap_growth", "Why Watch": "Key quality-growth bellwether tied to enterprise spending, cloud demand, AI infrastructure, and interest-rate sensitivity."},
    {"Ticker": "NVDA", "Company": "NVIDIA", "Sector / Lens": "AI semiconductors", "Bucket": "semis", "Why Watch": "Major index leadership driver; important for AI capex sentiment, semiconductor breadth, and high-multiple growth risk."},
    {"Ticker": "AMZN", "Company": "Amazon", "Sector / Lens": "Consumer / cloud", "Bucket": "consumer_growth", "Why Watch": "Combines consumer spending, logistics costs, cloud demand, and margin discipline."},
    {"Ticker": "GOOGL", "Company": "Alphabet", "Sector / Lens": "Digital advertising / AI", "Bucket": "mega_cap_growth", "Why Watch": "Ad demand and AI spending help gauge corporate confidence and mega-cap breadth."},
    {"Ticker": "META", "Company": "Meta Platforms", "Sector / Lens": "Digital advertising / AI", "Bucket": "mega_cap_growth", "Why Watch": "Useful read on ad budgets, consumer engagement, cost control, and investor appetite for profitable growth."},
    {"Ticker": "AVGO", "Company": "Broadcom", "Sector / Lens": "Semiconductors / infrastructure software", "Bucket": "semis", "Why Watch": "AI networking and infrastructure exposure; important for semiconductor breadth beyond NVIDIA."},
    {"Ticker": "AMD", "Company": "Advanced Micro Devices", "Sector / Lens": "Semiconductors / AI compute", "Bucket": "semis", "Why Watch": "Helps judge whether AI enthusiasm is broadening beyond one dominant chip leader."},
    {"Ticker": "JPM", "Company": "JPMorgan Chase", "Sector / Lens": "Banks / credit", "Bucket": "financials", "Why Watch": "Bank bellwether for credit quality, loan demand, deposit costs, and yield-curve sensitivity."},
    {"Ticker": "BAC", "Company": "Bank of America", "Sector / Lens": "Banks / rates", "Bucket": "financials", "Why Watch": "Highly relevant when yield-curve movement and deposit-cost pressure matter for financials."},
    {"Ticker": "GS", "Company": "Goldman Sachs", "Sector / Lens": "Capital markets", "Bucket": "financials", "Why Watch": "Useful read on deal activity, risk appetite, trading conditions, and institutional confidence."},
    {"Ticker": "V", "Company": "Visa", "Sector / Lens": "Payments / consumer", "Bucket": "consumer_quality", "Why Watch": "High-quality consumer-spending signal with global transaction exposure."},
    {"Ticker": "MA", "Company": "Mastercard", "Sector / Lens": "Payments / consumer", "Bucket": "consumer_quality", "Why Watch": "Confirms consumer and cross-border spending trends through payment volume."},
    {"Ticker": "XOM", "Company": "Exxon Mobil", "Sector / Lens": "Energy / crude oil", "Bucket": "energy", "Why Watch": "Direct read-through from crude oil, refining margins, and inflation-sensitive positioning."},
    {"Ticker": "CVX", "Company": "Chevron", "Sector / Lens": "Energy / crude oil", "Bucket": "energy", "Why Watch": "Large-cap energy confirmation signal alongside crude oil and the dollar."},
    {"Ticker": "COP", "Company": "ConocoPhillips", "Sector / Lens": "Energy / E&P", "Bucket": "energy", "Why Watch": "More direct upstream sensitivity to oil-price changes and energy risk appetite."},
    {"Ticker": "SLB", "Company": "SLB", "Sector / Lens": "Oil services", "Bucket": "energy", "Why Watch": "Useful read on energy capital spending and global drilling activity."},
    {"Ticker": "CAT", "Company": "Caterpillar", "Sector / Lens": "Industrials / global growth", "Bucket": "cyclical", "Why Watch": "Cyclical bellwether tied to infrastructure, commodities, construction, and global demand."},
    {"Ticker": "DE", "Company": "Deere", "Sector / Lens": "Industrials / agriculture", "Bucket": "cyclical", "Why Watch": "Gives a read on agriculture, equipment demand, credit sensitivity, and global cyclicals."},
    {"Ticker": "GE", "Company": "GE Aerospace", "Sector / Lens": "Industrials / aerospace", "Bucket": "cyclical", "Why Watch": "Industrial quality bellwether tied to aerospace demand and capital spending."},
    {"Ticker": "UNH", "Company": "UnitedHealth Group", "Sector / Lens": "Healthcare / defensive quality", "Bucket": "defensive", "Why Watch": "Defensive S&P 500 weight; useful if investors rotate away from cyclical or high-multiple growth."},
    {"Ticker": "LLY", "Company": "Eli Lilly", "Sector / Lens": "Healthcare growth", "Bucket": "defensive_growth", "Why Watch": "Large-cap healthcare growth leader; helps show whether investors favor quality growth outside technology."},
    {"Ticker": "JNJ", "Company": "Johnson & Johnson", "Sector / Lens": "Healthcare / defensive", "Bucket": "defensive", "Why Watch": "Defensive healthcare bellwether for risk-off rotation and quality demand."},
    {"Ticker": "COST", "Company": "Costco", "Sector / Lens": "Consumer staples / quality", "Bucket": "defensive_consumer", "Why Watch": "Quality consumer read; helpful when investors are testing household resilience."},
    {"Ticker": "WMT", "Company": "Walmart", "Sector / Lens": "Consumer staples / value consumer", "Bucket": "defensive_consumer", "Why Watch": "Strong read on value-focused consumer behavior and defensive retail demand."},
    {"Ticker": "PG", "Company": "Procter & Gamble", "Sector / Lens": "Consumer staples", "Bucket": "defensive_consumer", "Why Watch": "Defensive staples bellwether for margin resilience, pricing power, and risk-off rotation."},
    {"Ticker": "KO", "Company": "Coca-Cola", "Sector / Lens": "Staples / global dollar exposure", "Bucket": "defensive_consumer", "Why Watch": "Useful multinational staples read when the dollar is moving."},
    {"Ticker": "TSLA", "Company": "Tesla", "Sector / Lens": "High beta / consumer discretionary", "Bucket": "high_beta", "Why Watch": "High-beta sentiment gauge sensitive to rates, consumer demand, margins, and risk appetite."},
    {"Ticker": "HD", "Company": "Home Depot", "Sector / Lens": "Housing / consumer", "Bucket": "housing", "Why Watch": "Useful read-through for housing, renovation demand, mortgage-rate pressure, and consumer confidence."},
    {"Ticker": "LOW", "Company": "Lowe’s", "Sector / Lens": "Housing / consumer", "Bucket": "housing", "Why Watch": "Confirms housing-linked consumer spending and rate-sensitive demand trends."},
]

def select_rotating_company_watchlist(dashboard: pd.DataFrame, week_end: date, max_names: int = 12) -> List[Dict[str, str]]:
    """Rotates the company watchlist each run while keeping the selection tied to the macro backdrop."""
    rng = variation_rng("company_rotation")
    sp = get_row(dashboard, "S&P 500")
    ten = get_row(dashboard, "10-Year Treasury Yield")
    oil = get_row(dashboard, "WTI Crude Oil")
    dollar = get_row(dashboard, "Broad U.S. Dollar Index")
    hy = get_row(dashboard, "High Yield Credit Spread")
    vix = get_row(dashboard, "VIX Volatility Index")
    mortgage = get_row(dashboard, "30-Year Mortgage Rate")

    focus_buckets = set()
    # Always include index leadership.
    focus_buckets.update(["mega_cap_growth", "semis", "financials", "energy"])
    if ten is not None and ten.get("Direction") == "up":
        focus_buckets.update(["mega_cap_growth", "high_beta", "housing", "financials"])
    if ten is not None and ten.get("Direction") == "down":
        focus_buckets.update(["mega_cap_growth", "housing", "high_beta"])
    if oil is not None and oil.get("Direction") == "up":
        focus_buckets.update(["energy", "cyclical"])
    if dollar is not None and dollar.get("Direction") == "up":
        focus_buckets.update(["defensive_consumer", "mega_cap_growth"])
    if hy is not None and hy.get("Direction") == "up":
        focus_buckets.update(["financials", "defensive", "defensive_consumer"])
    if vix is not None and vix.get("Direction") == "up":
        focus_buckets.update(["defensive", "defensive_growth", "defensive_consumer"])
    if mortgage is not None and mortgage.get("Direction") == "up":
        focus_buckets.update(["housing", "financials", "consumer_quality"])
    if sp is not None and sp.get("Direction") == "up":
        focus_buckets.update(["semis", "high_beta", "cyclical"])

    priority = [x for x in SP500_COMPANY_WATCHLIST if x["Bucket"] in focus_buckets]
    others = [x for x in SP500_COMPANY_WATCHLIST if x["Bucket"] not in focus_buckets]
    rng.shuffle(priority)
    rng.shuffle(others)

    # Keep a few anchor weights, then rotate the rest.
    anchors = [x for x in SP500_COMPANY_WATCHLIST if x["Ticker"] in ["AAPL", "MSFT", "NVDA", "JPM", "XOM"]]
    rng.shuffle(anchors)
    selected = []
    seen = set()
    for group in [anchors[:3], priority, others]:
        for item in group:
            if item["Ticker"] in seen:
                continue
            selected.append(item)
            seen.add(item["Ticker"])
            if len(selected) >= max_names:
                return selected
    return selected

def fetch_yahoo_price_snapshot(ticker: str, week_end: date) -> Dict[str, str]:
    """Fetch last close and weekly change from Yahoo's public chart endpoint. Silent on failure."""
    try:
        start_dt = datetime.combine(week_end - timedelta(days=14), datetime.min.time())
        end_dt = datetime.combine(week_end + timedelta(days=3), datetime.min.time())
        period1 = int(start_dt.timestamp())
        period2 = int(end_dt.timestamp())
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        params = {"period1": period1, "period2": period2, "interval": "1d", "events": "history", "includeAdjustedClose": "true"}
        headers = {"User-Agent": f"{BRAND_NAME.replace(' ', '-')}/1.0"}
        r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return {"Last Price": "", "Weekly Change": "", "Price Date": ""}
        js = r.json()
        result = (js.get("chart", {}).get("result") or [None])[0]
        if not result:
            return {"Last Price": "", "Weekly Change": "", "Price Date": ""}
        ts = result.get("timestamp", []) or []
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", []) or []
        if not ts or not closes:
            return {"Last Price": "", "Weekly Change": "", "Price Date": ""}
        df = pd.DataFrame({"date": pd.to_datetime(ts, unit="s").date, "close": closes})
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"]).sort_values("date")
        df = df[df["date"] <= week_end]
        if df.empty:
            return {"Last Price": "", "Weekly Change": "", "Price Date": ""}
        latest = df.iloc[-1]
        prior_target = week_end - timedelta(days=7)
        prior_df = df[df["date"] <= prior_target]
        prior = prior_df.iloc[-1] if not prior_df.empty else df.iloc[0]
        latest_close = float(latest["close"])
        prior_close = float(prior["close"])
        chg = ((latest_close / prior_close) - 1) * 100 if prior_close else np.nan
        return {
            "Last Price": f"${latest_close:,.2f}",
            "Weekly Change": f"{chg:+.2f}%" if not pd.isna(chg) else "",
            "Price Date": latest["date"].isoformat() if hasattr(latest["date"], "isoformat") else str(latest["date"]),
        }
    except Exception:
        return {"Last Price": "", "Weekly Change": "", "Price Date": ""}

def fetch_sp500_company_watchlist(week_end: date, dashboard: pd.DataFrame) -> pd.DataFrame:
    rows = []
    selected = select_rotating_company_watchlist(dashboard, week_end, max_names=12)
    for item in selected:
        snap = fetch_yahoo_price_snapshot(item["Ticker"], week_end)
        row = {k: v for k, v in item.items() if k != "Bucket"}
        row.update(snap)
        rows.append(row)
        time.sleep(0.12)
    cols = ["Ticker", "Company", "Sector / Lens", "Last Price", "Weekly Change", "Why Watch"]
    return pd.DataFrame(rows)[cols]

# ----------------------------
# 7) Charts — borderless
# ----------------------------
def make_charts(data: Dict[str, pd.DataFrame], out_dir: Path, week_end: date) -> Dict[str, str]:
    chart_dir = out_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    chart_paths: Dict[str, str] = {}
    cutoff = pd.Timestamp(week_end - timedelta(days=180))

    for cfg in SERIES:
        if not cfg.chart:
            continue
        df = data.get(cfg.name, pd.DataFrame()).copy()
        if df.empty:
            continue
        df = df[df["date"] >= cutoff].copy()
        if df.empty:
            continue

        # Compact, newsletter-friendly chart sizing.
        # This keeps charts readable while preventing the report from becoming one huge scroll.
        fig, ax = plt.subplots(figsize=(6.8, 2.85), dpi=170)
        ax.plot(df["date"], df["value"], linewidth=1.45)
        ax.set_title(cfg.name, fontsize=13, fontname="Times New Roman", pad=7)
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.grid(True, alpha=0.16, linewidth=0.5)
        ax.tick_params(axis="both", labelsize=7.5, length=0, pad=2)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=4))
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5))

        # Remove all chart borders/spines.
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        fig.autofmt_xdate(rotation=0)
        fig.tight_layout(pad=0.45)

        fname = f"{safe_slug(cfg.name)}_{REPORT_DATE_STAMP}.png"
        path = chart_dir / fname
        fig.savefig(path, bbox_inches="tight", pad_inches=0.01, transparent=False)
        plt.close(fig)
        chart_paths[cfg.name] = str(path)
    return chart_paths

# ----------------------------
# 8) HTML / Markdown report builders
# ----------------------------
def html_escape(x) -> str:
    return html.escape(str(x), quote=True)

def chart_img_tag(path: str, output_dir: Path) -> str:
    try:
        rel = Path(path).resolve().relative_to(output_dir.resolve())
    except Exception:
        rel = Path(path).name
    return f'<img class="chart" src="{html_escape(str(rel))}" alt="Macro chart">'

def dashboard_display_table(dashboard: pd.DataFrame) -> str:
    if dashboard.empty:
        return ""
    cols = ["Category", "Series", "Latest Display", "Weekly Change", "Higher Usually Means"]
    show = dashboard[cols].copy()
    show = show.rename(columns={"Latest Display": "Latest"})
    return show.to_html(index=False, escape=True, border=0, classes="clean-table")

def next_watch_html(stock_watch: pd.DataFrame, commentary: Dict[str, object]) -> str:
    """Public-facing next-week section. No failed-fetch notes, no automation language."""
    watch_items = commentary.get("watchlist", []) or []
    bullets = "".join(f"<li>{html_escape(x)}</li>" for x in watch_items)
    table = ""
    if stock_watch is not None and not stock_watch.empty:
        table = stock_watch.to_html(index=False, escape=True, border=0, classes="clean-table stock-watch")
    intro = commentary.get("next_watch_intro") or "The next week should be evaluated through rates, credit, volatility, oil, and market leadership."
    company_note = commentary.get("company_note") or "These companies are useful market tells because they represent major S&P 500 weights or important macro-sensitive sectors."
    return f"""
    <h2>6. What We Should Be Watching Next</h2>
    <p>{html_escape(intro)}</p>
    <ul>{bullets}</ul>
    <h3>S&P 500 Companies to Monitor</h3>
    <p>{html_escape(company_note)}</p>
    {table}
    """

def build_html_report(
    output_dir: Path,
    dashboard: pd.DataFrame,
    commentary: Dict[str, object],
    headlines: pd.DataFrame,
    stock_watch: pd.DataFrame,
    chart_paths: Dict[str, str],
    week_start: date,
    week_end: date,
) -> str:
    table_html = dashboard_display_table(dashboard)
    next_watch_block = next_watch_html(stock_watch, commentary)

    opening_html = "".join(f"<p>{html_escape(x)}</p>" for x in commentary.get("opening", []))
    changed_html = "".join(f"<p>{html_escape(x)}</p>" for x in commentary.get("changed", []))
    watch_html = "".join(f"<li>{html_escape(x)}</li>" for x in commentary.get("watchlist", []))

    charts_html = ""
    if chart_paths:
        pieces = []
        for cfg in SERIES:
            p = chart_paths.get(cfg.name)
            if not p:
                continue
            pieces.append(f"<div class='chart-card'>{chart_img_tag(p, output_dir)}</div>")
        charts_html = "<div class='chart-grid'>" + "".join(pieces) + "</div>"

    html_text = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html_escape(BRAND_TOP_LINE)} — {html_escape(BRAND_SUB_LINE)}</title>
<style>
    @page {{ margin: 0.45in; }}
    html, body {{
        margin: 0;
        padding: 0;
        background: #ffffff;
        color: #111111;
        font-family: "Times New Roman", Times, serif;
        font-size: 12px;
        line-height: 1.42;
        text-align: left;
    }}
    .page {{
        max-width: 760px;
        margin: 0 auto;
        padding: 16px 16px 42px 16px;
        text-align: left;
    }}
    .brand-box {{
        text-align: center;
        margin: 6px auto 14px auto;
        line-height: 1.15;
    }}
    .brand-line {{
        display: inline-block;
        background: #e5e5e5;
        padding: 1px 5px;
        margin: 1px auto;
        font-size: 21px;
        font-weight: 700;
        text-decoration: underline;
        text-underline-offset: 2px;
    }}
    h1, h2, h3 {{
        font-family: "Times New Roman", Times, serif;
        font-size: 18px;
        font-weight: 700;
        line-height: 1.2;
        margin: 18px auto 8px auto;
        text-align: left;
        text-decoration: underline;
        text-underline-offset: 2px;
    }}
    .subline {{
        font-size: 12px;
        margin: 4px auto 14px auto;
    }}
    p {{
        font-size: 12px;
        max-width: 680px;
        margin: 7px auto;
        text-align: left;
    }}
    ul {{
        list-style-position: inside;
        padding-left: 0;
        margin: 8px auto 14px auto;
        max-width: 680px;
        text-align: left;
    }}
    li {{
        font-size: 12px;
        margin: 5px auto;
        text-align: left;
    }}
    .score-box {{
        display: inline-block;
        margin: 8px auto 14px auto;
        padding: 6px 14px;
        background: #f3f3f3;
        font-size: 12px;
        font-weight: 700;
    }}
    .clean-table {{
        width: 96%;
        margin: 10px auto 18px auto;
        border-collapse: collapse;
        border: 0;
        text-align: left;
        font-size: 12px;
    }}
    .clean-table th, .clean-table td {{
        border: 0;
        padding: 5px 6px;
        text-align: left;
        vertical-align: middle;
        font-size: 12px;
    }}
    .clean-table th {{
        font-weight: 700;
        background: #f1f1f1;
    }}
    .clean-table tr:nth-child(even) td {{
        background: #fafafa;
    }}
    a {{
        color: #111111;
        text-decoration: underline;
    }}
    .chart-grid {{
        width: min(980px, 100%);
        margin: 10px auto 20px auto;
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px 16px;
        text-align: center;
        justify-content: center;
        align-items: start;
    }}
    .chart-card {{
        margin: 0 auto;
        padding: 0;
        border: 0;
        box-shadow: none;
        outline: none;
        break-inside: avoid;
        page-break-inside: avoid;
    }}
    img.chart {{
        display: block;
        width: 100%;
        max-width: 100%;
        height: auto;
        margin: 0 auto;
        border: 0;
        outline: none;
        box-shadow: none;
    }}
    @media (max-width: 850px) {{
        .chart-grid {{
            width: 100%;
            margin: 10px 0 18px 0;
            grid-template-columns: 1fr;
        }}
    }}
    .divider {{
        height: 1px;
        background: #eeeeee;
        margin: 16px auto;
        width: 70%;
    }}
    .small-note {{
        font-size: 12px;
        color: #444444;
    }}
    @media print {{
        body {{ font-size: 12px; }}
        h1, h2, h3 {{ font-size: 18px; text-decoration: underline; }}
        .brand-line {{ font-size: 21px; text-decoration: underline; }}
        .page {{ max-width: 740px; padding: 8px 10px; }}
        .chart-grid {{ width: 100%; margin: 8px auto 18px auto; grid-template-columns: 1fr 1fr; gap: 10px 12px; text-align:center; }}
        .chart-card {{ break-inside: avoid; page-break-inside: avoid; }}
        img.chart {{ width: 100%; max-width: 100%; margin: 0; }}
    }}
</style>
</head>
<body>
<div class="page">
    <div class="brand-box">
        <div><span class="brand-line">{html_escape(BRAND_TOP_LINE)}</span></div>
        <div><span class="brand-line">{html_escape(BRAND_SUB_LINE)}</span></div>
    </div>

    <div class="subline">Published {REPORT_RELEASE_DATE.strftime('%A, %B %d, %Y')}</div>
    <div class="score-box">Macro Read: {html_escape(commentary.get('label', 'Mixed'))} | Score {html_escape(commentary.get('score', 0))}</div>

    <h2>1. This Week’s Setup</h2>
    <ul>{watch_html}</ul>

    <div class="divider"></div>

    <h2>2. Big Picture Macro Read</h2>
    {opening_html}

    <h2>3. What Shifted Last Week</h2>
    {changed_html}

    <h2>4. Macro Dashboard</h2>
    {table_html}

    <h2>5. Charts</h2>
    {charts_html}

    {next_watch_block}
</div>
</body>
</html>"""

    path = output_dir / "index.html"
    path.write_text(html_text, encoding="utf-8")
    return str(path)

def build_markdown_report(
    output_dir: Path,
    dashboard: pd.DataFrame,
    commentary: Dict[str, object],
    headlines: pd.DataFrame,
    stock_watch: pd.DataFrame,
    week_start: date,
    week_end: date,
) -> str:
    lines = []
    lines.append(f"# {BRAND_TOP_LINE}")
    lines.append(f"# {BRAND_SUB_LINE}")
    lines.append(f"Published {REPORT_RELEASE_DATE.strftime('%A, %B %d, %Y')}")
    lines.append("")
    lines.append(f"**Macro Read:** {commentary.get('label')} | Score {commentary.get('score')}")
    lines.append("")
    lines.append("## 1. This Week’s Setup")
    for item in commentary.get("watchlist", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 2. Big Picture Macro Read")
    for item in commentary.get("opening", []):
        lines.append(str(item))
        lines.append("")
    lines.append("## 3. What Shifted Last Week")
    for item in commentary.get("changed", []):
        lines.append(str(item))
        lines.append("")
    lines.append("## 4. Macro Dashboard")
    if not dashboard.empty:
        show = dashboard[["Category", "Series", "Latest Display", "Weekly Change", "Higher Usually Means"]].copy()
        show = show.rename(columns={"Latest Display": "Latest"})
        lines.append(show.to_markdown(index=False))
    lines.append("")
    lines.append("## 6. What We Should Be Watching Next")
    lines.append("The next week should be evaluated through the relationship between rates, credit, volatility, oil, and market leadership. The goal is not to predict every headline; the goal is to identify which signals confirm risk appetite and which signals challenge it.")
    lines.append("")
    for item in commentary.get("watchlist", []):
        lines.append(f"- {item}")
    if stock_watch is not None and not stock_watch.empty:
        lines.append("")
        lines.append("### S&P 500 Companies to Monitor")
        lines.append(stock_watch.to_markdown(index=False))
    path = output_dir / "newsletter.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)

# ----------------------------
# 9) Run everything
# ----------------------------
prior_start = WEEK_END - timedelta(days=LOOKBACK_DAYS)

print("Pulling macro data...")
data, used_ids = fetch_all_fred_data(prior_start, WEEK_END)
dashboard = build_dashboard(data, used_ids, WEEK_END)
commentary = generate_human_commentary(dashboard, WEEK_START, WEEK_END)
print("Building rotating S&P 500 company watchlist...")
stock_watch = fetch_sp500_company_watchlist(WEEK_END, dashboard)

if SKIP_GDELT:
    headlines = pd.DataFrame(columns=["Topic", "Title", "Source", "URL", "Seen Date"])
else:
    print("Pulling headline links...")
    headlines = fetch_macro_headlines(WEEK_START, WEEK_END)

chart_paths: Dict[str, str] = {}
if CREATE_CHARTS:
    print("Creating charts...")
    chart_paths = make_charts(data, OUTPUT_DIR, WEEK_END)

# Save clean CSV files
show_cols = [
    "Category", "Series", "FRED ID", "Latest Date", "Latest Display", "Weekly Change",
    "Higher Usually Means", "Why It Matters"
]
dashboard_path = DATA_DIR / f"macro_dashboard_{REPORT_DATE_STAMP}.csv"
raw_path = DATA_DIR / f"raw_fred_data_{REPORT_DATE_STAMP}.csv"
headline_path = DATA_DIR / f"headline_links_{REPORT_DATE_STAMP}.csv"
stock_watch_path = DATA_DIR / f"sp500_company_watchlist_{REPORT_DATE_STAMP}.csv"

dashboard.to_csv(dashboard_path, index=False)
headlines.to_csv(headline_path, index=False)
stock_watch.to_csv(stock_watch_path, index=False)

raw_frames = []
for name, df in data.items():
    if df.empty:
        continue
    tmp = df.copy()
    tmp["series_name"] = name
    tmp["fred_id"] = used_ids.get(name, "")
    raw_frames.append(tmp[["series_name", "fred_id", "date", "value"]])

if raw_frames:
    pd.concat(raw_frames, ignore_index=True).to_csv(raw_path, index=False)
else:
    pd.DataFrame(columns=["series_name", "fred_id", "date", "value"]).to_csv(raw_path, index=False)

html_path = build_html_report(OUTPUT_DIR, dashboard, commentary, headlines, stock_watch, chart_paths, WEEK_START, WEEK_END)
md_path = build_markdown_report(OUTPUT_DIR, dashboard, commentary, headlines, stock_watch, WEEK_START, WEEK_END)

manifest = {
    "brand": BRAND_NAME,
    "week_start": WEEK_START.isoformat(),
    "week_end": WEEK_END.isoformat(),
    "release_date": REPORT_RELEASE_DATE.isoformat(),
    "date_stamp": REPORT_DATE_STAMP,
    "created_at": datetime.now().isoformat(timespec="seconds"),
    "output_dir": str(OUTPUT_DIR),
    "html_report": html_path,
    "markdown_report": md_path,
    "dashboard_csv": str(dashboard_path),
    "headline_links_csv": str(headline_path),
    "sp500_company_watchlist_csv": str(stock_watch_path),
    "raw_fred_data_csv": str(raw_path),
    "series_used": used_ids,
    "gdelt_headline_count": int(len(headlines)),
}
manifest_path = OUTPUT_DIR / f"manifest_{REPORT_DATE_STAMP}.json"
manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

print("\nDONE")
print(f"HTML report:     {html_path}")
print(f"Markdown report: {md_path}")
print(f"Dashboard CSV:   {dashboard_path}")
print(f"Headline CSV:    {headline_path}")
print(f"S&P Watch CSV:   {stock_watch_path}")
print(f"Raw FRED CSV:    {raw_path}")
print(f"Manifest:        {manifest_path}")

if OPEN_HTML_AFTER:
    try:
        webbrowser.open(Path(html_path).resolve().as_uri())
    except Exception:
        pass

# Clean preview inside Jupyter
try:
    from IPython.display import display, HTML
    display_cols = ["Category", "Series", "Latest Display", "Weekly Change", "Higher Usually Means"]
    display(dashboard[display_cols] if not dashboard.empty else pd.DataFrame())
    display(HTML(f'<p style="font-family: Times New Roman; font-size:12px; text-align:left;">Created: <b>{html_path}</b></p>'))
except Exception:
    pass


# =============================

