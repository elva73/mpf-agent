import os
import json
import numpy as np
import pandas as pd
import scipy.optimize as sco
from anthropic import Anthropic

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
                    "description": "Portfolio YTD return in percent.",
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
            },
            "required": [
                "portfolio_ytd",
                "benchmark_ytd",
                "target_return",
                "beats_benchmark",
                "meets_target",
                "recommended_allocation",
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
        "annualised_return_pct": round(42.64 / 3, 2),
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
        "annualised_return_pct": round(8.18 / 3, 2),
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
        "annualised_return_pct": round(24.71 / 3, 2),
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
        "annualised_return_pct": round(37.33 / 3, 2),
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
        "annualised_return_pct": round(17.25 / 3, 2),
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
_INVESTOR_TARGET_RETURN = 8.0   # percent per annum


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_get_portfolio_state(tool_input: dict) -> str:
    current_ytd = sum(
        f["allocation_pct"] / 100 * f["ytd_return_pct"] for f in _PORTFOLIO
    )
    return json.dumps({
        "investor_target_annual_return_pct": _INVESTOR_TARGET_RETURN,
        "portfolio_weighted_ytd_return_pct": round(current_ytd, 2),
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

    # ── Bounds: 2 %–40 % per fund (ensures minimum diversification) ─────────
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
        "note": (
            "Volatilities estimated from risk ratings. "
            "Correlations estimated from asset classes. "
            "Minimum 2 % per fund, maximum 40 % per fund."
        ),
    })


def tool_build_weekly_email(tool_input: dict) -> str:
    portfolio_ytd: float = tool_input["portfolio_ytd"]
    benchmark_ytd: float = tool_input["benchmark_ytd"]
    target_return: float = tool_input["target_return"]
    beats_benchmark: bool = tool_input["beats_benchmark"]
    meets_target: bool = tool_input["meets_target"]
    recommended: dict = tool_input["recommended_allocation"]

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

    # Format allocation table
    alloc_lines = "\n".join(
        f"  • {fund}: {pct}%" for fund, pct in recommended.items()
    )

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
─── Recommended Reallocation ──────────────────────────
{alloc_lines}

This optimised allocation is designed to meet your {target_return:.1f}% target
with minimum portfolio risk, maintaining bond exposure for downside protection
and diversification across multiple asset classes.

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

def run_agent() -> None:
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
"""

    user_prompt = """
Review the investor's MPF portfolio.
Compare current performance with the target return and Hang Seng Index benchmark.
If needed, generate an optimised reallocation and draft the weekly investor email alert.
"""

    messages = [{"role": "user", "content": user_prompt}]

    while True:
        response = client.messages.create(
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
            break

        # Execute tool calls and feed results back
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                try:
                    result = dispatch_tool(block.name, block.input)
                except Exception as exc:
                    result = json.dumps({
                        "error": f"Tool execution failed for '{block.name}': {exc}"
                    })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    run_agent()
