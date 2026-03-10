# Architecture

## Repository layout

```
New Project/
├── data/
│   └── funds.json        # Master fund data file (22 funds + metadata)
├── mpf_agent.py          # AI agent — all backend logic
├── test_email.py         # Local test: generates email preview without API
├── my-next-app/          # Next.js landing page
│   ├── app/
│   │   ├── layout.tsx             # Root layout (arrow fn, Header + Footer)
│   │   ├── page.tsx               # Home page (arrow fn)
│   │   ├── globals.css            # Global Tailwind styles
│   │   └── components/
│   │       ├── Header.tsx         # Nav bar + "가입하기" CTA button
│   │       └── Footer.tsx         # Footer + "문의하기" CTA button
│   ├── public/                    # Static assets (SVGs)
│   ├── next.config.ts
│   ├── tailwind.config (via postcss)
│   └── package.json
├── README.md
├── ARCHITECTURE.md
└── CLAUDE.md             # Project coding conventions
```

---

## MPF Agent (`mpf_agent.py`)

### Component overview

```
┌─────────────────────────────────────────────────────────────┐
│                         __main__                            │
│   --scheduler │ --monthly │ --remind │ (default)            │
└───────┬─────────────────────────────────┬───────────────────┘
        │                                 │
        ▼                                 ▼
 start_scheduler()               run_monthly_job()
 (daily cron loop,             send_fund_update_request()
  fires 1st of month)          run_agent(send_result=True)
        │                                 │
        └──────────────┬──────────────────┘
                       │
                       ▼
                 run_agent()
                       │
                       ▼
           ┌─────────────────────┐
           │  _call_api_with_    │  ← exponential backoff retry
           │  retry()            │    (429, 529, timeout, connection)
           └────────┬────────────┘
                    │  Anthropic Messages API (claude-opus-4-6)
                    ▼
           ┌─────────────────────┐
           │   Claude Opus 4.6   │
           │   (agent loop)      │
           └────────┬────────────┘
                    │  tool_use blocks
                    ▼
           ┌─────────────────────┐
           │   dispatch_tool()   │
           └────────┬────────────┘
                    │
       ┌────────────┼──────────────────────┐
       ▼            ▼                      ▼
get_portfolio_  get_fund_universe   get_benchmark_state
   state()           ()                   ()
       │
       └────────────┬──────────────────────┐
                    ▼                      ▼
        optimize_allocation()     build_weekly_email()
        (Markowitz MVO,           ├─ alert logic (4 severity levels)
         SLSQP solver,            ├─ optimisation stats header
         forecast calc)           │    (solver status, return/target/gap,
                    │             │     new return/vol/sharpe)
                    │             ├─ current portfolio holdings table
                    │             │    (loop over _PORTFOLIO,
                    │             │     bar = "█" * int(alloc/2))
                    │             ├─ ASCII round chart
                    │             │    (CHART_WIDTH=60, SYMBOLS list,
                    │             │     proportional cells per fund)
                    │             ├─ reallocation highlights
                    │             │    (↑/↓ arrows, was X%, 1yr return)
                    │             ├─ optimization rationale paragraph
                    │             │    (auto-generated from fund data)
                    │             ├─ 5yr/3yr forecast bullet summaries
                    └────────────►└─ next steps
                    passes:
                    expected_annual_return_pct,
                    portfolio_volatility_pct,
                    sharpe_ratio,
                    forecast_comparison
                                           │
                                           ▼
                                    send_email()  ← SMTP
```

### Agent loop

1. Send `user_prompt` to Claude with the `TOOLS` schema
2. Claude responds with `tool_use` blocks
3. Each tool call is dispatched to the corresponding Python function via `dispatch_tool()`
4. Results are fed back as `tool_result` blocks
5. Loop continues until `stop_reason != "tool_use"`
6. On completion, if `send_result=True` and `build_weekly_email` was called, the formatted email is sent via SMTP
7. Email result is captured **locally** in `run_agent` via `json.loads` — no global state

### Test script (`test_email.py`)

Bypasses the Claude API entirely for local testing. Outputs **only** the complete formatted email body to stdout — no debug lines, no separators.

```
test_email.py
    │
    ├─► tool_optimize_allocation()   # runs MVO directly
    │       └─► opt_result (allocation, sharpe, vol, forecast)
    │
    └─► tool_build_weekly_email()    # renders email directly
            ├─ portfolio_ytd      ← from opt_result
            ├─ benchmark_ytd      ← from _BENCHMARK
            ├─ target_return      ← from _INVESTOR_TARGET_RETURN
            ├─ beats_benchmark    ← computed locally
            ├─ meets_target       ← computed locally
            ├─ recommended_allocation   ← from opt_result
            ├─ expected_annual_return_pct ← from opt_result
            ├─ portfolio_volatility_pct   ← from opt_result
            ├─ sharpe_ratio               ← from opt_result
            └─ forecast_comparison        ← from opt_result
                    │
                    ▼
            print(email_result["email"])   # clean output only
```

### Data flow

```
_PORTFOLIO (8 funds, static)
    │
    ├─► tool_get_portfolio_state()
    │       └─► weighted 1yr return + holdings JSON
    │           note: 1yr trailing, not calendar-year YTD
    │
_FUND_UNIVERSE (8 funds, static)
    │
    ├─► tool_get_fund_universe()
    │       └─► candidate funds for optimisation
    │
    └─► tool_optimize_allocation(target_return=20.0)
            ├─► expected returns array (1yr trailing proxy)
            ├─► volatility estimates (from risk rating)
            │       High=20%, Medium=12%, Low-Med=7%, Low=5%
            ├─► heuristic correlation matrix (asset-class based)
            │       equity↔bond=0.10, same class=0.85, diff class=0.45
            ├─► covariance matrix
            ├─► SLSQP minimise variance subject to:
            │       • weights sum to 1
            │       • weighted return ≥ 20% (overall portfolio target)
            │       • bond allocation ≥ 5%
            │       • 2% ≤ each weight ≤ 40%
            │
            └─► output: allocation, expected_return, volatility,
                        sharpe_ratio, forecast_comparison
                    │
                    ▼
                forecast_comparison:
                    annual_return: { current_pct, new_pct, improvement_pct }
                    3_year: { current_cumulative_pct, new_cumulative_pct,
                              current_value_hkd, new_value_hkd,
                              gain_vs_current_hkd }
                    5_year: { same structure as 3_year }
                    formula: ((1 + r/100)^n - 1) * 100
                    base: HKD 100 invested today
```

### Tool schemas (`TOOLS`)

| Tool | Required inputs | Output |
|---|---|---|
| `get_portfolio_state` | *(none)* | Holdings, weighted 1yr return, investor target, note |
| `get_fund_universe` | *(none)* | 8 fund codes, asset class, expected return, risk, is_bond |
| `get_benchmark_state` | *(none)* | HSI level and YTD return |
| `optimize_allocation` | `target_return`, `fund_codes?` | Allocation %, expected return, volatility, Sharpe, `forecast_comparison` |
| `build_weekly_email` | `portfolio_ytd`, `benchmark_ytd`, `target_return`, `beats_benchmark`, `meets_target`, `recommended_allocation`, `expected_annual_return_pct`, `portfolio_volatility_pct`, `sharpe_ratio`, `forecast_comparison` (10 required fields) | Formatted email string + alert metadata |

### `build_weekly_email` — Current Portfolio Holdings table

The holdings table is built by looping over `_PORTFOLIO` and rendering one row per fund:

```python
for f in _PORTFOLIO:
    bar = "█" * int(f["allocation_pct"] / 2)   # 1 block ≈ 2%
    # columns: fund name (42 chars), alloc %, 1yr return %, risk level, bar
```

Each row shows: fund name, allocation %, 1yr return %, risk level, and an inline bar chart. The bar length is `int(allocation_pct / 2)` so each `█` represents approximately 2% allocation.

### `build_weekly_email` — ASCII Round Chart

The round chart is a proportional bar spanning exactly 60 characters (`CHART_WIDTH = 60`), with 8 distinct block symbols assigned to each fund:

```python
CHART_WIDTH = 60
SYMBOLS = ["▓", "░", "▒", "■", "□", "▪", "▫", "◆"]

for idx, f in enumerate(_PORTFOLIO):
    sym   = SYMBOLS[idx % len(SYMBOLS)]
    cells = max(1, round(f["allocation_pct"] / 100 * CHART_WIDTH))
    chart_bar += sym * cells
    legend    += f"  {sym} {f['fund']:<42} {f['allocation_pct']:>5.1f}%\n"

chart_bar = chart_bar[:CHART_WIDTH].ljust(CHART_WIDTH)   # trim/pad to exact width
```

A legend below the bar shows each symbol with its fund name and allocation percentage.

### `build_weekly_email` — Optimization Rationale generation

The rationale paragraph is **auto-generated in Python** from `_FUND_UNIVERSE` and `_PORTFOLIO` data — it does not rely on Claude to write it. This guarantees it always appears in the email.

```python
# Inputs used to build the paragraph:
new_return       → expected_annual_return_pct   (from optimize_allocation)
curr_ret         → annual_return.current_pct    (from forecast_comparison)
improvement      → new_return - curr_ret
yr3_new          → 3_year.new_cumulative_pct    (from forecast_comparison)
new_sharpe       → sharpe_ratio                 (from optimize_allocation)
new_vol          → portfolio_volatility_pct     (from optimize_allocation)
n_funds          → len(recommended_allocation)
n_classes        → count of unique asset classes in recommended funds
bond_funds       → funds where is_bond=True
bond_pct         → sum of weights for bond funds
```

Example output:
```
This rebalanced allocation drives an expected return of ~20.0% per annum
(~72.8% cumulative over 3 years), projecting toward the 20.0–22% target.
We achieve superior diversification across 8 asset classes and an
improvement in a Sharpe ratio of 1.78, while annualised volatility of
9.0% ensures downside risk remains within tolerance. Bond exposure of
9.7% (Global Bond Fund) provides additional downside protection against
equity market drawdowns.
```

### `build_weekly_email` — full email structure

```
Subject: Weekly MPF Portfolio Update [ACTION REQUIRED]?

1. Performance Summary
   portfolio return / HSI YTD / target / vs benchmark / vs target

2. Alert Banner
   ✅  On Track              — beats benchmark AND meets 20% target
   ⚠️  Benchmark Alert       — portfolio < HSI only
   ⚠️  Target Return Not Met — portfolio < 20% target only
   🚨  URGENT                — portfolio below both benchmark and target

3. Optimisation Stats
   Solver: ✅ Converged successfully
   Current portfolio return: XX.X% | Target: XX.X% | Gap: ±X.X%
   New optimised return: XX.X% | Volatility: X.XX% | Sharpe: X.XXX

4. Current Portfolio Holdings
   Fund name (42 chars)  Alloc%  1yr Rtn%  Risk level  █ bar (each █ ≈ 2%)
   (one row per fund, all 8 funds from _PORTFOLIO)

5. Current Allocation — Round Chart
   ┌────────────────────────────────────────────────────────────┐
   │▓▓▓▓▓▓▓▓▓░░░░░░░░▒▒▒▒▒▒▒▒■■■■■■■□□□□□□▪▪▪▪▪▪▫▫▫▫◆◆◆◆│
   └────────────────────────────────────────────────────────────┘
   ▓ Fund Name 1   XX.X%
   ░ Fund Name 2   XX.X%
   ...  (legend for all 8 funds)

6. Recommended Reallocation Highlights
   * ↑/↓ Fund Name: XX.X% (was XX.X%) — ±XX.X% 1yr return
   (one bullet per fund, ↑=increase ↓=decrease →=unchanged)

7. Optimization Rationale  ← auto-generated Python paragraph
   "This rebalanced allocation drives an expected return of ~XX.X%
    per annum (~XX.X% cumulative over 3 years), projecting toward
    the XX.X–XX% target..."

8. Forecast Summaries (per HKD 100 invested)
   5-year forecast:
     * Current portfolio → HKD XXX.XX (annual: XX.X%)
     * New portfolio     → HKD XXX.XX (+X.XX% annual improvement)
     * Gain vs current   → +HKD XX.XX
   3-year forecast:
     * Current portfolio → HKD XXX.XX
     * New portfolio     → HKD XXX.XX
     * Gain vs current   → +HKD XX.XX

9. Next Steps
   1. Review reallocation [PROMPTLY if action required]
   2. Log in to MPF trustee portal to submit switch
   3. Allow 3–5 business days for switch to take effect
   4. Next weekly update will confirm new allocation performance
```

### Key constants

| Constant | Value | Purpose |
|---|---|---|
| `_INVESTOR_TARGET_RETURN` | `20.0` | Overall portfolio annual return target (%) — loaded from `data/funds.json` |
| `_BENCHMARK` | HSI 19,845.32 / YTD 5.6% | Performance benchmark — loaded from `data/funds.json` |
| `_PORTFOLIO` | 8 funds | Current holdings — loaded from `data/funds.json` (`in_portfolio=true`) |
| `_FUND_UNIVERSE` | 22 funds | Full optimisation universe — loaded from `data/funds.json` (all funds) |
| `_MAX_RETRIES` | `3` | API retry attempts on transient errors |
| `_RETRY_BACKOFF_BASE` | `2.0s` | Base for exponential backoff (2^attempt seconds) |
| Per-fund bounds | `(0.02, 0.40)` | 2%–40% weight range per fund |
| Bond floor | `0.05` | Minimum 5% in bond fund(s) |
| Risk-free rate | `4.0%` | HK approx., used for Sharpe ratio |
| `CHART_WIDTH` | `60` | Total character width of the ASCII round chart |
| `SYMBOLS` | `["▓","░","▒","■","□","▪","▫","◆"]` | 8 distinct block symbols for round chart |

### `data/funds.json` — master fund data file

All fund data is stored in `data/funds.json` and loaded at startup by `_load_fund_data()`.
To update fund figures monthly, edit only this file — no Python code changes needed.

**Top-level structure:**
```json
{
  "metadata": {
    "investor_target_return_pct": 20.0,
    "benchmark": { "index": "...", "level": 19845.32, "ytd_return_pct": 5.6 }
  },
  "funds": [ { ...one object per fund... } ]
}
```

**Per-fund fields:**

| Field | Type | Notes |
|---|---|---|
| `code` | str | Short uppercase identifier (e.g. `"GROWTH"`, `"GL_BD"`) |
| `name` | str | Full display name |
| `asset_class` | str | Classification used for MVO correlation matrix |
| `risk` | str | `"High"` / `"Medium"` / `"Low to Medium"` / `"Low"` / `"Medium to High"` |
| `is_bond` | bool | `true` for bond/money-market funds (affects MVO correlation + bond floor) |
| `in_portfolio` | bool | `true` for the 8 currently-held funds |
| `allocation_pct` | float\|null | Current weight %; non-null only when `in_portfolio=true` |
| `return_1m_pct` … `return_5yr_pct` | float\|null | Performance figures from fund sheet |
| `return_since_launch_pct` | float\|null | Cumulative since inception |
| `launch_date` | str | ISO 8601 date |
| `return_since_restructuring_pct` | float\|null | Only for funds that were restructured |
| `restructuring_date` | str\|null | ISO 8601 date; null if not applicable |

**Derived fields (computed at load time, not stored):**
- `annualised_return_pct` → `((1 + return_3yr_pct/100)^(1/3) - 1) * 100`, fallback to `return_1yr_pct`
- `expected_return_pct` → equals `return_1yr_pct` (1yr trailing proxy for MVO)

**Fund universe (22 funds total):**

| Code | Fund | In Portfolio |
|---|---|---|
| `GROWTH` | Growth Fund | ✓ |
| `GL_BD` | Global Bond Fund | ✓ |
| `HK_CN_EQ` | Hong Kong and Chinese Equity Fund | ✓ |
| `EU_EQ` | European Equity Fund | ✓ |
| `CN_EQ` | Chinese Equity Fund | ✓ |
| `NA_EQ` | North American Equity Fund | ✓ |
| `HSI_IDX` | Hang Seng Index Tracking Fund | ✓ |
| `AP_EQ` | Asia Pacific Equity Fund | ✓ |
| `AGE65_DR` | Age 65 Plus Fund (with de-risking nature) | — |
| `AGE65_NDR` | Age 65 Plus Fund (without de-risking nature) | — |
| `BAL` | Balanced Fund | — |
| `CORE_DR` | Core Accumulation Fund (with de-risking nature) | — |
| `CORE_NDR` | Core Accumulation Fund (without de-risking nature) | — |
| `GL_EQ` | Global Equity Fund | — |
| `GUAR` | Guaranteed Fund | — |
| `HSCEI_IDX` | Hang Seng China Enterprises Index Tracking Fund | — |
| `MPF_CONS` | MPF Conservative Fund | — |
| `STABLE` | Stable Fund | — |
| `VC_AP_EQ` | ValueChoice Asia Pacific Equity Tracker Fund | — |
| `VC_BAL` | ValueChoice Balanced Fund | — |
| `VC_EU_EQ` | ValueChoice Europe Equity Tracker Fund | — |
| `VC_NA_EQ` | ValueChoice North America Equity Tracker Fund | — |

### Annualised return formula

3-year cumulative returns are converted to annualised figures:

```
annualised = ((1 + cumulative/100)^(1/years) - 1) * 100
```

Applied to 5 of the 8 funds that have 3yr history. The remaining 3 (North American Equity, HSI Tracking, Asia Pacific Equity) use 1yr return directly as only 1yr data is available.

### API resilience (`_call_api_with_retry`)

```
Retry conditions:
  APIConnectionError   → always retry (network issue)
  APITimeoutError      → always retry (timeout)
  APIStatusError 429   → rate limited, retry with backoff
  APIStatusError 529   → API overloaded, retry with backoff
  Other APIStatusError → raise immediately (auth error, bad request, etc.)

Backoff schedule: 2^attempt seconds → 1s, 2s, 4s
Max attempts: 3
```

---

## Next.js Landing Page (`my-next-app/`)

### Tech stack

| Layer | Technology |
|---|---|
| Framework | Next.js 16 (App Router) |
| Language | TypeScript |
| Styling | Tailwind CSS v4 |
| Runtime | React 19 |

### Component tree

```
RootLayout (layout.tsx)       ← const arrow fn, export default
├── <Header />                ← const arrow fn, "가입하기" CTA button
├── <main className="flex-1">
│   └── <Home />              ← const arrow fn (page.tsx), export default
└── <Footer />                ← const arrow fn, "문의하기" CTA button
```

### Conventions (from CLAUDE.md)

- All React components **must** be arrow functions:
  ```tsx
  const Foo = () => { ... };
  export default Foo;
  ```
- All major CTA buttons **must** use these exact Tailwind classes:
  ```
  bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-md shadow-md
  ```
