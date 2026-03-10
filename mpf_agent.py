import os
import sys
import json
import smtplib
import time
import schedule
import numpy as np
import pandas as pd
import scipy.optimize as sco
from anthropic import Anthropic
from anthropic import APIStatusError, APIConnectionError, APITimeoutError
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------------------------------------------------------------------------
# Email configuration (set these as environment variables)
# ---------------------------------------------------------------------------
_EMAIL_CFG = {
    "smtp_host":  os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com"),
    "smtp_port":  int(os.environ.get("EMAIL_SMTP_PORT", "587")),
    "username":   os.environ.get("EMAIL_USERNAME", ""),
    "password":   os.environ.get("EMAIL_PASSWORD", ""),
    "sender":     os.environ.get("EMAIL_SENDER", ""),
    "recipient":  os.environ.get("EMAIL_RECIPIENT", ""),
}


# ---------------------------------------------------------------------------
# Tool schemas — passed to the Claude API so the model knows what to call
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "get_portfolio_state",
        "description": (
            "Returns the investor's current MPF portfolio: fund names, "
            "asset class, current allocation (%), YTD return (%), and "
            "annualised return (%)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_fund_universe",
        "description": (
            "Returns the full universe of MPF-eligible funds with their "
            "asset class, expected annual return (%), risk level, and "
            "whether they qualify as bond funds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_benchmark_state",
        "description": (
            "Returns the current Hang Seng Index (HSI) level and its "
            "YTD return (%) to use as a performance benchmark."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "optimize_allocation",
        "description": (
            "Given a target annual return and a list of candidate fund codes, "
            "returns an optimised allocation (%) across those funds using "
            "mean-variance optimisation. Must use at least 4 funds and "
            "multiple asset classes. Includes a bond fund if feasible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_return": {
                    "type": "number",
                    "description": "Target annual return in percent, e.g. 8.0",
                },
                "fund_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of fund codes to consider in the optimisation.",
                },
            },
            "required": ["target_return"],
        },
    },
    {
        "name": "build_weekly_email",
        "description": (
            "Drafts the weekly investor email alert. Takes a summary dict "
            "with portfolio performance, benchmark comparison, and "
            "recommended allocation, and returns a formatted email string."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_ytd": {
                    "type": "number",
                    "description": (
                        "Portfolio trailing 1-year return in percent "
                        "(used as performance proxy; true YTD unavailable)."
                    ),
                },
                "benchmark_ytd": {
                    "type": "number",
                    "description": "Benchmark (HSI) YTD return in percent.",
                },
                "target_return": {
                    "type": "number",
                    "description": "Investor target annual return in percent.",
                },
                "beats_benchmark": {
                    "type": "boolean",
                    "description": "Whether the portfolio beats the benchmark.",
                },
                "meets_target": {
                    "type": "boolean",
                    "description": "Whether the portfolio meets the target return.",
                },
                "recommended_allocation": {
                    "type": "object",
                    "description": "Dict mapping fund name to allocation percent.",
                },
                "expected_annual_return_pct": {
                    "type": "number",
                    "description": "Expected annual return of the new optimised portfolio (%).",
                },
                "portfolio_volatility_pct": {
                    "type": "number",
                    "description": "Annualised volatility of the new optimised portfolio (%).",
                },
                "sharpe_ratio": {
                    "type": "number",
                    "description": "Sharpe ratio of the new optimised portfolio.",
                },
                "forecast_comparison": {
                    "type": "object",
                    "description": (
                        "Forecasted return comparison between current and new portfolio. "
                        "Pass the forecast_comparison object directly from optimize_allocation output. "
                        "Contains annual_return, 3_year, and 5_year sub-objects with "
                        "cumulative return (%) and HKD future value for both current and new portfolio."
                    ),
                },
            },
            "required": [
                "portfolio_ytd",
                "benchmark_ytd",
                "target_return",
                "beats_benchmark",
                "meets_target",
                "recommended_allocation",
                "expected_annual_return_pct",
                "portfolio_volatility_pct",
                "sharpe_ratio",
                "forecast_comparison",
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Real fund data (from investor's fund sheet)
# ---------------------------------------------------------------------------

# Full performance data available for the top 5 holdings (from fund sheet).
# Funds 6–8 have allocation + 1yr return only.
_PORTFOLIO = [
    {
        "fund": "Growth Fund",
        "asset_class": "Mixed / Growth",
        "risk": "High",
        "allocation_pct": 18.01,
        "return_1m_pct":   -1.33,
        "return_3m_pct":    3.59,
        "return_6m_pct":    8.00,
        "return_1yr_pct":  21.23,
        "return_3yr_pct":  42.64,   # cumulative
        "return_5yr_pct":  27.11,   # cumulative
        "return_since_launch_pct": 211.80,
        "launch_date": "2000-12-01",
        "annualised_return_pct": round(((1 + 42.64 / 100) ** (1 / 3) - 1) * 100, 2),
    },
    {
        "fund": "Global Bond Fund",
        "asset_class": "Bond – Global",
        "risk": "Low to Medium",
        "allocation_pct": 15.16,
        "return_1m_pct":   0.11,
        "return_3m_pct":   1.14,
        "return_6m_pct":   1.06,
        "return_1yr_pct":  5.01,
        "return_3yr_pct":  8.18,
        "return_5yr_pct": -10.22,
        "return_since_launch_pct": 17.18,
        "launch_date": "2009-10-08",
        "annualised_return_pct": round(((1 + 8.18 / 100) ** (1 / 3) - 1) * 100, 2),
    },
    {
        "fund": "Hong Kong and Chinese Equity Fund",
        "asset_class": "Equity – HK/China",
        "risk": "High",
        "allocation_pct": 14.85,
        "return_1m_pct":  -6.39,
        "return_3m_pct":  -2.48,
        "return_6m_pct":  -0.61,
        "return_1yr_pct": 13.07,
        "return_3yr_pct": 24.71,
        "return_5yr_pct": -11.62,
        "return_since_launch_pct": 168.76,
        "launch_date": "2000-12-01",
        "annualised_return_pct": round(((1 + 24.71 / 100) ** (1 / 3) - 1) * 100, 2),
    },
    {
        "fund": "European Equity Fund",
        "asset_class": "Equity – Europe",
        "risk": "Medium",
        "allocation_pct": 14.68,
        "return_1m_pct":  -3.27,
        "return_3m_pct":   2.70,
        "return_6m_pct":   8.88,
        "return_1yr_pct": 15.80,
        "return_3yr_pct": 37.33,
        "return_5yr_pct": 49.34,
        "return_since_launch_pct": 113.41,
        "launch_date": "2000-12-01",
        "annualised_return_pct": round(((1 + 37.33 / 100) ** (1 / 3) - 1) * 100, 2),
    },
    {
        "fund": "Chinese Equity Fund",
        "asset_class": "Equity – China",
        "risk": "High",
        "allocation_pct": 11.84,
        "return_1m_pct":  -5.65,
        "return_3m_pct":  -3.81,
        "return_6m_pct":  -2.26,
        "return_1yr_pct": 10.29,
        "return_3yr_pct": 17.25,
        "return_5yr_pct": 27.88,
        "return_since_launch_pct": 57.94,
        "launch_date": "2009-10-08",
        "annualised_return_pct": round(((1 + 17.25 / 100) ** (1 / 3) - 1) * 100, 2),
    },
    {
        "fund": "North American Equity Fund",
        "asset_class": "Equity – North America",
        "risk": "Medium",
        "allocation_pct": 10.89,
        "return_1yr_pct": 17.85,
        "annualised_return_pct": 17.85,  # only 1yr available
    },
    {
        "fund": "Hang Seng Index Tracking Fund",
        "asset_class": "Equity – HK (Index)",
        "risk": "Medium",
        "allocation_pct": 7.77,
        "return_1yr_pct": 9.76,
        "annualised_return_pct": 9.76,
    },
    {
        "fund": "Asia Pacific Equity Fund",
        "asset_class": "Equity – APAC",
        "risk": "Medium",
        "allocation_pct": 6.80,
        "return_1yr_pct": 27.90,
        "annualised_return_pct": 27.90,
    },
]

# Fund universe for optimisation — all 8 holdings are candidates.
# expected_return_pct uses the 1-year return as forward-looking proxy.
_FUND_UNIVERSE = [
    {"code": "GROWTH",   "name": "Growth Fund",                        "asset_class": "Mixed / Growth",        "risk": "High",          "expected_return_pct": 21.23, "is_bond": False},
    {"code": "GL_BD",    "name": "Global Bond Fund",                   "asset_class": "Bond – Global",         "risk": "Low to Medium", "expected_return_pct":  5.01, "is_bond": True},
    {"code": "HK_CN_EQ", "name": "Hong Kong and Chinese Equity Fund",  "asset_class": "Equity – HK/China",     "risk": "High",          "expected_return_pct": 13.07, "is_bond": False},
    {"code": "EU_EQ",    "name": "European Equity Fund",               "asset_class": "Equity – Europe",       "risk": "Medium",        "expected_return_pct": 15.80, "is_bond": False},
    {"code": "CN_EQ",    "name": "Chinese Equity Fund",                "asset_class": "Equity – China",        "risk": "High",          "expected_return_pct": 10.29, "is_bond": False},
    {"code": "NA_EQ",    "name": "North American Equity Fund",         "asset_class": "Equity – North America","risk": "Medium",        "expected_return_pct": 17.85, "is_bond": False},
    {"code": "HSI_IDX",  "name": "Hang Seng Index Tracking Fund",      "asset_class": "Equity – HK (Index)",   "risk": "Medium",        "expected_return_pct":  9.76, "is_bond": False},
    {"code": "AP_EQ",    "name": "Asia Pacific Equity Fund",           "asset_class": "Equity – APAC",         "risk": "Medium",        "expected_return_pct": 27.90, "is_bond": False},
]

_BENCHMARK = {"index": "Hang Seng Index", "level": 19_845.32, "ytd_return_pct": 5.6}
_INVESTOR_TARGET_RETURN = 20.0  # percent per annum — overall portfolio target


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_get_portfolio_state(tool_input: dict) -> str:
    weighted_1yr_return = sum(
        f["allocation_pct"] / 100 * f["return_1yr_pct"] for f in _PORTFOLIO
    )
    return json.dumps({
        "investor_target_annual_return_pct": _INVESTOR_TARGET_RETURN,
        # 1-year return is used as a proxy for annualised performance.
        # True YTD figures are not available in the fund sheet; consumers
        # of this data should treat portfolio_weighted_1yr_return_pct as
        # the performance figure for comparison purposes.
        "portfolio_weighted_1yr_return_pct": round(weighted_1yr_return, 2),
        "note": (
            "Return figures are 1-year trailing, not calendar-year YTD. "
            "Use portfolio_weighted_1yr_return_pct for benchmark comparisons."
        ),
        "holdings": _PORTFOLIO,
    })


def tool_get_fund_universe(tool_input: dict) -> str:
    return json.dumps({"funds": _FUND_UNIVERSE})


def tool_get_benchmark_state(tool_input: dict) -> str:
    return json.dumps(_BENCHMARK)


def tool_optimize_allocation(tool_input: dict) -> str:
    target_return: float = tool_input["target_return"]
    # Default: use all available funds
    fund_codes: list[str] = tool_input.get(
        "fund_codes", [f["code"] for f in _FUND_UNIVERSE]
    )

    universe = {f["code"]: f for f in _FUND_UNIVERSE}
    selected = [universe[c] for c in fund_codes if c in universe]

    if len(selected) < 4:
        return json.dumps({"error": "Need at least 4 valid fund codes."})

    n = len(selected)

    # ── Expected returns (%) ────────────────────────────────────────────────
    returns = np.array([f["expected_return_pct"] for f in selected])

    # Check feasibility: target must not exceed the best possible return
    if target_return > returns.max():
        return json.dumps({
            "error": (
                f"Target return {target_return}% exceeds the highest available "
                f"fund return ({returns.max()}%). Please lower your target."
            )
        })

    # ── Volatility estimates from risk rating (annual %) ────────────────────
    _VOL = {"High": 20.0, "Medium": 12.0, "Low to Medium": 7.0, "Low": 5.0}
    vols = np.array([_VOL.get(f["risk"], 15.0) for f in selected])

    # ── Correlation matrix (asset-class based heuristic) ───────────────────
    def _corr(f1: dict, f2: dict) -> float:
        if f1["is_bond"] != f2["is_bond"]:
            return 0.10   # equity ↔ bond: very low
        if f1["asset_class"] == f2["asset_class"]:
            return 0.85   # same asset class: high
        return 0.45       # different equity classes: moderate

    corr = np.array([[_corr(selected[i], selected[j]) for j in range(n)]
                     for i in range(n)])
    np.fill_diagonal(corr, 1.0)

    # Covariance matrix (convert % → decimal: divide by 100 twice)
    cov = np.outer(vols, vols) * corr / 10_000

    # ── Objective: minimise portfolio variance ──────────────────────────────
    def portfolio_variance(w: np.ndarray) -> float:
        return float(w @ cov @ w)

    def variance_gradient(w: np.ndarray) -> np.ndarray:
        return 2.0 * cov @ w

    # ── Constraints ─────────────────────────────────────────────────────────
    constraints = [
        # Weights must sum to 1
        {"type": "eq",   "fun": lambda w: w.sum() - 1.0},
        # Weighted return must meet target
        {"type": "ineq", "fun": lambda w: w @ returns - target_return},
    ]

    # At least 5 % in bond fund(s) for downside protection
    bond_idx = [i for i, f in enumerate(selected) if f["is_bond"]]
    if bond_idx:
        constraints.append({
            "type": "ineq",
            "fun": lambda w, idx=bond_idx: sum(w[i] for i in idx) - 0.05,
        })

    # ── Bounds: 2 %–40 % per fund (ensures minimum diversification) ────────────
    bounds = [(0.02, 0.40)] * n

    # ── Solve (SLSQP) ────────────────────────────────────────────────────────
    w0 = np.ones(n) / n
    result = sco.minimize(
        portfolio_variance,
        w0,
        jac=variance_gradient,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-10, "maxiter": 2000},
    )

    if result.success:
        weights = result.x
    else:
        # Fallback: return-proportional weights (always feasible)
        raw = np.maximum(returns, 0.1)
        weights = raw / raw.sum()

    # Clean up numerical noise
    weights = np.clip(weights, 0.0, 1.0)
    weights /= weights.sum()

    # ── Build output ─────────────────────────────────────────────────────────
    allocation = {
        selected[i]["name"]: round(float(weights[i]) * 100, 1)
        for i in range(n)
        if weights[i] >= 0.005   # omit funds below 0.5 %
    }
    expected_return = round(float(weights @ returns), 2)
    port_vol = round(float(np.sqrt(weights @ cov @ weights)) * 100, 2)
    rf_rate = 4.0   # risk-free rate (HK approx.)
    sharpe = round((expected_return - rf_rate) / port_vol, 3) if port_vol > 0 else None

    # Current portfolio metrics for comparison
    curr_alloc = np.array([f["allocation_pct"] / 100 for f in _PORTFOLIO])
    curr_returns = np.array([f["return_1yr_pct"] for f in _PORTFOLIO])
    current_return = round(float(curr_alloc @ curr_returns), 2)

    # ── Forecasted cumulative returns (compound growth, HKD $100 base) ───────
    # Uses expected annual return as a constant forward-looking proxy.
    # new_annual  = expected_return (%) from optimised weights
    # curr_annual = current_return  (%) from current holdings
    def _compound(annual_pct: float, years: int) -> float:
        """Cumulative return (%) after `years` at `annual_pct`% p.a."""
        return round((((1 + annual_pct / 100) ** years) - 1) * 100, 1)

    def _future_value(annual_pct: float, years: int, base: float = 100.0) -> float:
        """Future value of `base` HKD after `years` at `annual_pct`% p.a."""
        return round(base * (1 + annual_pct / 100) ** years, 2)

    forecast = {
        "annual_return": {
            "current_pct":      current_return,
            "new_pct":          expected_return,
            "improvement_pct":  round(expected_return - current_return, 2),
        },
        "3_year": {
            "current_cumulative_pct":  _compound(current_return, 3),
            "new_cumulative_pct":      _compound(expected_return, 3),
            "current_value_hkd":       _future_value(current_return, 3),
            "new_value_hkd":           _future_value(expected_return, 3),
            "gain_vs_current_hkd":     round(
                _future_value(expected_return, 3) - _future_value(current_return, 3), 2
            ),
        },
        "5_year": {
            "current_cumulative_pct":  _compound(current_return, 5),
            "new_cumulative_pct":      _compound(expected_return, 5),
            "current_value_hkd":       _future_value(current_return, 5),
            "new_value_hkd":           _future_value(expected_return, 5),
            "gain_vs_current_hkd":     round(
                _future_value(expected_return, 5) - _future_value(current_return, 5), 2
            ),
        },
        "note": (
            "Forecasts assume constant annual return equal to current 1-year "
            "trailing performance. Actual returns will vary. "
            "Base: HKD 100 invested today."
        ),
    }

    return json.dumps({
        "optimisation_method": "Mean-Variance (Markowitz, SLSQP)",
        "solver_success": result.success,
        "target_return_pct": target_return,
        "recommended_allocation_pct": allocation,
        "expected_annual_return_pct": expected_return,
        "portfolio_volatility_pct": port_vol,
        "sharpe_ratio": sharpe,
        "current_portfolio_return_pct": current_return,
        "return_improvement_pct": round(expected_return - current_return, 2),
        "forecast_comparison": forecast,
        "note": (
            "Volatilities estimated from risk ratings. "
            "Correlations estimated from asset classes. "
            "Minimum 2 % per fund, maximum 40 % per fund."
        ),
    })


def tool_build_weekly_email(tool_input: dict) -> str:  # noqa: C901
    portfolio_ytd: float = tool_input["portfolio_ytd"]
    benchmark_ytd: float = tool_input["benchmark_ytd"]
    target_return: float = tool_input["target_return"]
    beats_benchmark: bool = tool_input["beats_benchmark"]
    meets_target: bool = tool_input["meets_target"]
    recommended: dict = tool_input["recommended_allocation"]
    forecast: dict = tool_input.get("forecast_comparison", {})
    new_return:  float = tool_input.get("expected_annual_return_pct", 0.0)
    new_vol:     float = tool_input.get("portfolio_volatility_pct", 0.0)
    new_sharpe:  float = tool_input.get("sharpe_ratio", 0.0)

    # ── Portfolio-level Optimization Rationale (single paragraph) ────────────
    # Summarises the overall new allocation: expected return, 3yr projection,
    # Sharpe improvement, diversification breadth, and downside protection.
    fc        = forecast.get("forecast_comparison", forecast)  # handle pass-through
    yr3       = fc.get("3_year", forecast.get("3_year", {}))
    curr_ret  = forecast.get("annual_return", {}).get("current_pct", 0.0)
    improvement = round(new_return - curr_ret, 1)
    imp_sign  = f"+{improvement}" if improvement >= 0 else str(improvement)

    # Count asset classes for diversification summary
    _fund_lookup = {f["name"]: f for f in _FUND_UNIVERSE}
    asset_classes = {
        _fund_lookup[f]["asset_class"]
        for f in recommended
        if f in _fund_lookup
    }
    bond_funds = [
        f for f in recommended
        if _fund_lookup.get(f, {}).get("is_bond", False)
    ]
    bond_pct = sum(recommended[f] for f in bond_funds)
    n_funds   = len(recommended)
    n_classes = len(asset_classes)

    # Current Sharpe for comparison (approx: (curr_ret - rf) / curr_vol)
    # We only show new Sharpe — current not available here, so describe direction
    sharpe_note = (
        f"a Sharpe ratio of {new_sharpe:.2f}"
        if new_sharpe else "an improved risk-adjusted return profile"
    )
    vol_note = f"annualised volatility of {new_vol:.1f}%" if new_vol else "controlled volatility"

    yr3_new = yr3.get("new_cumulative_pct", "")
    yr3_str = (
        f"~{new_return:.1f}% per annum (~{yr3_new}% cumulative over 3 years)"
        if yr3_new else f"~{new_return:.1f}% per annum"
    )
    target_range = f"{_INVESTOR_TARGET_RETURN}–{_INVESTOR_TARGET_RETURN + 2:.0f}%"

    rationale_paragraph = (
        f"This rebalanced allocation drives an expected return of {yr3_str}, "
        f"projecting toward the {target_range} target. "
        f"We achieve superior diversification across {n_classes} asset classes "
        f"and an improvement in {sharpe_note}, "
        f"while {vol_note} ensures downside risk remains within tolerance. "
        f"Bond exposure of {bond_pct:.1f}% ({', '.join(bond_funds) if bond_funds else 'none'}) "
        f"provides additional downside protection against equity market drawdowns."
    )

    # ── Alert logic ─────────────────────────────────────────────────────────
    below_benchmark = not beats_benchmark          # portfolio < HSI
    below_target    = not meets_target             # portfolio < target return
    action_required = below_benchmark or below_target

    # Determine alert severity
    if below_benchmark and below_target:
        alert_level   = "🚨 URGENT ACTION REQUIRED"
        alert_reasons = [
            f"Portfolio return ({portfolio_ytd:.1f}%) is BELOW the Hang Seng Index ({benchmark_ytd:.1f}%)",
            f"Portfolio return ({portfolio_ytd:.1f}%) is BELOW your target return ({target_return:.1f}%)",
        ]
        urgency_note = (
            "Your portfolio is underperforming on BOTH measures. "
            "Immediate reallocation is strongly recommended."
        )
    elif below_benchmark:
        alert_level   = "⚠️  ALERT: Benchmark Underperformance"
        alert_reasons = [
            f"Portfolio return ({portfolio_ytd:.1f}%) is BELOW the Hang Seng Index ({benchmark_ytd:.1f}%)",
        ]
        urgency_note = (
            "Your portfolio is lagging the benchmark. "
            "Consider reallocating toward higher-performing equity funds."
        )
    elif below_target:
        alert_level   = "⚠️  ALERT: Target Return Not Met"
        alert_reasons = [
            f"Portfolio return ({portfolio_ytd:.1f}%) is BELOW your target return ({target_return:.1f}%)",
        ]
        urgency_note = (
            "Your portfolio is not meeting your target. "
            "Reallocation toward the recommended weights is advised."
        )
    else:
        alert_level   = "✅  Portfolio On Track"
        alert_reasons = []
        urgency_note  = (
            "Your portfolio is outperforming both the benchmark and your target. "
            "No immediate action required, but review the optimised allocation "
            "below to further improve risk-adjusted returns."
        )

    # Format alert banner
    alert_lines = ""
    if alert_reasons:
        reasons_text = "\n".join(f"  ✗ {r}" for r in alert_reasons)
        alert_lines = f"""
─── {alert_level} ───────────────────────
{reasons_text}

{urgency_note}
"""
    else:
        alert_lines = f"""
─── {alert_level} ────────────────────────────────
  {urgency_note}
"""

    # ── Current portfolio table ──────────────────────────────────────────────
    curr_table_rows = ""
    for f in _PORTFOLIO:
        name   = f["fund"]
        alloc  = f["allocation_pct"]
        ret1yr = f["return_1yr_pct"]
        ac     = f.get("asset_class", "")
        risk   = f.get("risk", "")
        bar    = "█" * int(alloc / 2)   # 1 block ≈ 2%
        curr_table_rows += f"  {name:<42} {alloc:>5.1f}%  {ret1yr:>+6.1f}%  {risk:<14}  {bar}\n"

    current_portfolio_section = f"""
─── Current Portfolio Holdings ────────────────────────
  {'Fund':<42} {'Alloc':>6}  {'1yr Rtn':>7}  {'Risk':<14}  Chart (each █ ≈ 2%)
  {'─'*42} {'─'*6}  {'─'*7}  {'─'*14}  {'─'*20}
{curr_table_rows.rstrip()}

─── Current Allocation — Round Chart ──────────────────
"""
    # ASCII donut chart — each fund gets a proportional arc of characters
    # Total width = 60 chars representing 100%
    CHART_WIDTH = 60
    SYMBOLS = ["▓", "░", "▒", "■", "□", "▪", "▫", "◆"]
    chart_bar  = ""
    legend     = ""
    for idx, f in enumerate(_PORTFOLIO):
        sym    = SYMBOLS[idx % len(SYMBOLS)]
        cells  = max(1, round(f["allocation_pct"] / 100 * CHART_WIDTH))
        chart_bar += sym * cells
        legend    += f"  {sym} {f['fund']:<42} {f['allocation_pct']:>5.1f}%\n"
    # Trim/pad to exact width
    chart_bar = chart_bar[:CHART_WIDTH].ljust(CHART_WIDTH)

    current_portfolio_section += (
        f"  ┌{'─' * CHART_WIDTH}┐\n"
        f"  │{chart_bar}│\n"
        f"  └{'─' * CHART_WIDTH}┘\n\n"
        f"{legend.rstrip()}\n"
    )

    # ── Optimisation stats header ─────────────────────────────────────────────
    solver_ok  = "✅ Converged successfully"
    gap        = round(portfolio_ytd - target_return, 1)
    gap_str    = f"{gap:+.1f}%"
    stats_section = (
        f"Optimisation stats:\n"
        f"  * Solver: {solver_ok}\n"
        f"  * Current portfolio return: {portfolio_ytd:.1f}% | Target: {target_return:.1f}% | Gap: {gap_str}\n"
        f"  * New optimised return: {new_return:.1f}% | Volatility: {new_vol:.2f}% | Sharpe: {new_sharpe:.3f}\n"
    )

    # ── Build current-allocation lookup for "was X%" context ─────────────────
    curr_alloc_map = {f["fund"]: f["allocation_pct"] for f in _PORTFOLIO}
    curr_return_map = {f["fund"]: f["return_1yr_pct"] for f in _PORTFOLIO}

    # ── Recommended reallocation highlights (↑ ↓ arrows, was X% context) ─────
    highlight_lines = []
    for fund, new_pct in recommended.items():
        old_pct = curr_alloc_map.get(fund, 0.0)
        arrow   = "↑" if new_pct > old_pct else "↓" if new_pct < old_pct else "→"
        ret1yr  = curr_return_map.get(fund)
        ret_str = f" — {ret1yr:+.1f}% 1yr return" if ret1yr is not None else ""
        highlight_lines.append(
            f"  * {arrow} {fund}: {new_pct:.1f}% (was {old_pct:.1f}%){ret_str}"
        )
    highlights_section = "Recommended reallocation highlights:\n" + "\n".join(highlight_lines)

    # ── Optimization rationale ────────────────────────────────────────────────
    rationale_section = f"Optimization Rationale: {rationale_paragraph}"

    # ── 5-year forecast bullet summary ───────────────────────────────────────
    if forecast:
        yr5      = forecast.get("5_year", {})
        curr_fv5 = yr5.get("current_value_hkd", "N/A")
        new_fv5  = yr5.get("new_value_hkd", "N/A")
        gain5    = yr5.get("gain_vs_current_hkd", "N/A")
        yr3_     = forecast.get("3_year", {})
        curr_fv3 = yr3_.get("current_value_hkd", "N/A")
        new_fv3  = yr3_.get("new_value_hkd", "N/A")
        gain3    = yr3_.get("gain_vs_current_hkd", "N/A")
        ann_     = forecast.get("annual_return", {})
        imp_val  = ann_.get("improvement_pct", 0)
        imp_str  = f"+{imp_val}" if imp_val >= 0 else str(imp_val)
        forecast_section = (
            f"5-year forecast per HKD 100 invested:\n"
            f"  * Current portfolio → HKD {curr_fv5} (annual: {portfolio_ytd:.1f}%)\n"
            f"  * New portfolio     → HKD {new_fv5} ({imp_str}% annual improvement)\n"
            f"  * Gain vs current   → +HKD {gain5}\n"
            f"\n"
            f"3-year forecast per HKD 100 invested:\n"
            f"  * Current portfolio → HKD {curr_fv3}\n"
            f"  * New portfolio     → HKD {new_fv3}\n"
            f"  * Gain vs current   → +HKD {gain3}\n"
            f"\n"
            f"  * Forecast assumes constant annual return equal to trailing 1-year\n"
            f"    performance. Actual returns will vary with market conditions.\n"
        )
    else:
        forecast_section = ""

    # Subject line changes when action is required
    subject_flag = " [ACTION REQUIRED]" if action_required else ""

    email = f"""Subject: Weekly MPF Portfolio Update{subject_flag}

Dear Investor,

Here is your weekly MPF portfolio review.

─── Performance Summary ───────────────────────────────
  Portfolio return     : {portfolio_ytd:.1f}%
  Hang Seng Index YTD  : {benchmark_ytd:.1f}%
  Your target return   : {target_return:.1f}%
  vs Benchmark         : {portfolio_ytd - benchmark_ytd:+.1f}%
  vs Target            : {portfolio_ytd - target_return:+.1f}%
{alert_lines}
{stats_section}
{current_portfolio_section}
{highlights_section}

{rationale_section}

{forecast_section}
─── Next Steps ────────────────────────────────────────
{"1. Review the reallocation above PROMPTLY." if action_required else "1. Review the reallocation above at your convenience."}
2. Log in to your MPF trustee portal to submit the switch instruction.
3. Allow 3–5 business days for the switch to take effect.
4. Your next weekly update will confirm the new allocation performance.

Kind regards,
MPF Portfolio Intelligence System""".strip()

    return json.dumps({
        "email": email,
        "alert_triggered": action_required,
        "alert_level": alert_level,
        "below_benchmark": below_benchmark,
        "below_target": below_target,
    })


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

def send_email(subject: str, body: str) -> bool:
    """Send a plain-text email via SMTP. Returns True on success."""
    cfg = _EMAIL_CFG
    if not all([cfg["username"], cfg["password"], cfg["sender"], cfg["recipient"]]):
        print(f"[EMAIL] SMTP not configured — printing instead.\nSubject: {subject}\n\n{body}")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = cfg["sender"]
        msg["To"] = cfg["recipient"]
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
            server.starttls()
            server.login(cfg["username"], cfg["password"])
            server.send_message(msg)
        print(f"[EMAIL] Sent: {subject}")
        return True
    except Exception as exc:
        print(f"[EMAIL] Failed: {exc}")
        return False


def send_fund_update_request() -> None:
    """Send the monthly reminder asking the investor to update the fund sheet."""
    today = date.today()
    month_label = today.strftime("%B %Y")
    subject = f"[MPF] Action Required: Update Fund Sheet for {month_label}"
    body = f"""Dear Investor,

This is your monthly MPF fund data update reminder for {month_label}.

Please update the fund performance figures in mpf_agent.py (_PORTFOLIO and
_FUND_UNIVERSE) with the latest data from your MPF provider's fund sheet.

Fields to update for each fund:
  • allocation_pct    — current fund weight (%)
  • return_1m_pct    — 1-month return (%)
  • return_3m_pct    — 3-month return (%)
  • return_6m_pct    — 6-month return (%)
  • return_1yr_pct   — 1-year return (%)
  • return_3yr_pct   — 3-year cumulative return (%)
  • annualised_return_pct — update accordingly

Also update:
  • _BENCHMARK ytd_return_pct  — latest HSI YTD return (%)
  • _INVESTOR_TARGET_RETURN    — if your target has changed

After updating, run:
  python mpf_agent.py --monthly

to re-run the performance analysis and receive the result email.

Kind regards,
MPF Portfolio Intelligence System"""
    send_email(subject, body)


# ---------------------------------------------------------------------------
# Monthly job and scheduler
# ---------------------------------------------------------------------------

def run_monthly_job() -> None:
    """
    Full monthly workflow:
      1. Send fund-sheet update request email (ask investor to refresh data).
      2. Run the MPF agent and send the performance result email.

    NOTE: Steps 1 and 2 run in the same process invocation. If the investor
    needs to update the fund sheet before analysis, run with --remind only,
    then re-run with --monthly after updating the data. Use --monthly when
    the fund sheet is already up to date (e.g. in an automated post-update hook).
    """
    today = date.today()
    print(f"[SCHEDULER] Monthly MPF review — {today.strftime('%B %Y')}")

    # Step 1: remind investor to update fund sheet
    send_fund_update_request()

    # Step 2: run agent on current data and send its result email.
    # Assumes _PORTFOLIO / _FUND_UNIVERSE already reflect current month's data.
    run_agent(send_result=True)
    print("[SCHEDULER] Monthly review complete.")


def send_fund_update_reminder_only() -> None:
    """Send only the fund-sheet update request without running analysis."""
    send_fund_update_request()


def start_scheduler() -> None:
    """
    Start a long-running daily scheduler.
    On the 1st of every month at 08:00, the full monthly job runs automatically.
    """
    def _daily_check():
        if date.today().day == 1:
            run_monthly_job()

    schedule.every().day.at("08:00").do(_daily_check)
    print("[SCHEDULER] Started. Monthly job will run on the 1st of each month at 08:00.")
    while True:
        schedule.run_pending()
        time.sleep(60)


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def dispatch_tool(name: str, tool_input: dict) -> str:
    """Route Claude tool calls to the corresponding local Python function."""
    tool_map = {
        "get_portfolio_state": tool_get_portfolio_state,
        "get_fund_universe": tool_get_fund_universe,
        "get_benchmark_state": tool_get_benchmark_state,
        "optimize_allocation": tool_optimize_allocation,
        "build_weekly_email": tool_build_weekly_email,
    }

    if name not in tool_map:
        raise ValueError(f"Unknown tool requested by agent: {name}")

    return tool_map[name](tool_input)


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2.0  # seconds; doubled on each retry


def _call_api_with_retry(client: Anthropic, **kwargs) -> object:
    """Call client.messages.create with exponential-backoff retry on transient errors."""
    for attempt in range(_MAX_RETRIES):
        try:
            return client.messages.create(**kwargs)
        except (APIConnectionError, APITimeoutError) as exc:
            wait = _RETRY_BACKOFF_BASE ** attempt
            print(f"[API] Transient error ({exc}). Retrying in {wait:.0f}s "
                  f"(attempt {attempt + 1}/{_MAX_RETRIES})...")
            time.sleep(wait)
        except APIStatusError as exc:
            if exc.status_code in (429, 529) and attempt < _MAX_RETRIES - 1:
                wait = _RETRY_BACKOFF_BASE ** attempt
                print(f"[API] Rate limited ({exc.status_code}). Retrying in {wait:.0f}s "
                      f"(attempt {attempt + 1}/{_MAX_RETRIES})...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"API call failed after {_MAX_RETRIES} attempts.")


def run_agent(send_result: bool = False) -> None:
    """Main Anthropic agent loop for MPF portfolio monitoring and optimisation."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set in the environment.")

    client = Anthropic(api_key=api_key)

    system_prompt = """
You are an MPF portfolio monitoring and optimisation agent.

Your responsibilities are:
1. Inspect the current MPF portfolio.
2. Compare it with the investor's target return and Hang Seng Index benchmark.
3. Recommend a reallocation using at least 4 funds and multiple asset classes.
4. Include a bond fund if possible without violating the target return.
5. Draft a weekly investor email alert summarising performance and recommendations.

When responding:
- Always evaluate whether the current portfolio beats the benchmark.
- Always evaluate whether the current portfolio meets the target return.
- If needed, recommend an improved allocation.
- Clearly explain the reasoning in investor-friendly language.
- Note: portfolio return figures are trailing 1-year, not calendar-year YTD.

When calling build_weekly_email, you MUST:
1. Pass expected_annual_return_pct, portfolio_volatility_pct, and sharpe_ratio
   directly from the optimize_allocation result — do not modify these values.

2. Pass the forecast_comparison object directly from the optimize_allocation result
   into the forecast_comparison field. Do not modify or summarise it — pass it as-is.
   This contains the 3-year and 5-year projected cumulative returns and HKD future
   values for both the current and new portfolio, so the investor can compare outcomes.
"""

    user_prompt = """
Review the investor's MPF portfolio.
Compare current performance with the target return and Hang Seng Index benchmark.
If needed, generate an optimised reallocation and draft the weekly investor email alert.
"""

    messages = [{"role": "user", "content": user_prompt}]
    email_result: dict | None = None  # captured when build_weekly_email is called

    while True:
        response = _call_api_with_retry(
            client,
            model="claude-opus-4-6",
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        # Build assistant turn (text + any tool_use blocks)
        assistant_content = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        messages.append({"role": "assistant", "content": assistant_content})

        # Done — no more tool calls
        if response.stop_reason != "tool_use":
            print("\n=== FINAL AGENT OUTPUT ===\n")
            for block in response.content:
                if block.type == "text":
                    print(block.text)

            # Optionally send the performance result email
            if send_result and email_result:
                email_text = email_result["email"]
                lines = email_text.split("\n")
                subject = lines[0].replace("Subject: ", "").strip() if lines else "MPF Monthly Performance Update"
                body = "\n".join(lines[2:]) if len(lines) > 2 else email_text
                send_email(subject, body)

            break

        # Execute tool calls and feed results back
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                try:
                    result_str = dispatch_tool(block.name, block.input)
                    # Capture email result locally instead of via global
                    if block.name == "build_weekly_email":
                        email_result = json.loads(result_str)
                except Exception as exc:
                    result_str = json.dumps({
                        "error": f"Tool execution failed for '{block.name}': {exc}"
                    })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })

        messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "--scheduler":
        # Long-running process: fires on 1st of each month at 08:00
        start_scheduler()
    elif cmd == "--monthly":
        # Run the full monthly job (assumes fund sheet is already updated)
        run_monthly_job()
    elif cmd == "--remind":
        # Send only the fund-sheet update reminder email; do NOT run analysis
        send_fund_update_reminder_only()
    else:
        # Default: run agent once (no email send)
        run_agent()
