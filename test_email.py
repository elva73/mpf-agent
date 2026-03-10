"""
test_email.py — Generate a sample MPF weekly email without calling the Claude API.

Run:
    python test_email.py

This calls tool_optimize_allocation() and tool_build_weekly_email() directly
using the real portfolio data from mpf_agent.py, then prints the full email body.
No ANTHROPIC_API_KEY required.
"""

import json
import sys
import os

# Make sure we can import from the same directory
sys.path.insert(0, os.path.dirname(__file__))

from mpf_agent import (
    tool_optimize_allocation,
    tool_build_weekly_email,
    _INVESTOR_TARGET_RETURN,
    _BENCHMARK,
    _PORTFOLIO,
    _FUND_UNIVERSE,
)

# ── Step 1: Run the optimiser with the 20% overall target ───────────────────
opt_result = json.loads(tool_optimize_allocation({
    "target_return": _INVESTOR_TARGET_RETURN,
    "fund_codes": [f["code"] for f in _FUND_UNIVERSE],
}))

# ── Step 2: Derive values Claude would normally compute ─────────────────────
portfolio_ytd               = opt_result["current_portfolio_return_pct"]
benchmark_ytd               = _BENCHMARK["ytd_return_pct"]
target_return               = _INVESTOR_TARGET_RETURN
beats_benchmark             = portfolio_ytd > benchmark_ytd
meets_target                = portfolio_ytd >= target_return
recommended_allocation      = opt_result["recommended_allocation_pct"]
forecast_comparison         = opt_result["forecast_comparison"]
expected_annual_return_pct  = opt_result["expected_annual_return_pct"]
portfolio_volatility_pct    = opt_result["portfolio_volatility_pct"]
sharpe_ratio                = opt_result["sharpe_ratio"]

# ── Step 3: Build and print the full email ───────────────────────────────────
email_result = json.loads(tool_build_weekly_email({
    "portfolio_ytd":              portfolio_ytd,
    "benchmark_ytd":              benchmark_ytd,
    "target_return":              target_return,
    "beats_benchmark":            beats_benchmark,
    "meets_target":               meets_target,
    "recommended_allocation":     recommended_allocation,
    "expected_annual_return_pct": expected_annual_return_pct,
    "portfolio_volatility_pct":   portfolio_volatility_pct,
    "sharpe_ratio":               sharpe_ratio,
    "forecast_comparison":        forecast_comparison,
}))

print(email_result["email"])
