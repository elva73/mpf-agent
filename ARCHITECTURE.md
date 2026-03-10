# Architecture

## Repository layout

```
New Project/
├── mpf_agent.py          # AI agent — all backend logic
├── my-next-app/          # Next.js landing page
│   ├── app/
│   │   ├── layout.tsx             # Root layout (Header + Footer wrapper)
│   │   ├── page.tsx               # Home page
│   │   ├── globals.css            # Global Tailwind styles
│   │   └── components/
│   │       ├── Header.tsx         # Site header with CTA button
│   │       └── Footer.tsx         # Site footer with CTA button
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
        (Markowitz MVO,           ├─ alert logic
         SLSQP solver,            ├─ allocation table
         forecast calc)           ├─ optimization rationale
                    │             ├─ 3yr/5yr forecast table
                    │             └─ next steps
                    └──────────────────────┘
                                           │
                                           ▼
                                    send_email()  ← SMTP
```

### Agent loop

The agent runs a standard tool-use loop:

1. Send `user_prompt` to Claude with the `TOOLS` schema
2. Claude responds with `tool_use` blocks
3. Each tool call is dispatched to the corresponding Python function via `dispatch_tool()`
4. Results are fed back as `tool_result` blocks
5. Loop continues until `stop_reason != "tool_use"`
6. On completion, if `send_result=True` and `build_weekly_email` was called, the formatted email is sent via SMTP
7. Email result is captured locally in `run_agent` (no global state) via `json.loads` on the tool response

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
            │       • weighted return ≥ 20% (overall target)
            │       • bond allocation ≥ 5%
            │       • 2% ≤ each weight ≤ 40%
            └─► forecast_comparison (compound growth)
                    ├─► 3yr: cumulative %, HKD value (current vs new)
                    └─► 5yr: cumulative %, HKD value (current vs new)
                            formula: ((1 + r/100)^n - 1) * 100
                            base: HKD 100 invested today
```

### Tool schemas (`TOOLS`)

| Tool | Input | Output |
|---|---|---|
| `get_portfolio_state` | *(none)* | Holdings, weighted 1yr return, investor target |
| `get_fund_universe` | *(none)* | All 8 fund codes, asset class, expected return, risk |
| `get_benchmark_state` | *(none)* | HSI level and YTD return |
| `optimize_allocation` | `target_return`, `fund_codes?` | Optimal weights, Sharpe ratio, `forecast_comparison` |
| `build_weekly_email` | `portfolio_ytd`, `benchmark_ytd`, `target_return`, `beats_benchmark`, `meets_target`, `recommended_allocation`, `optimization_rationale`, `forecast_comparison` | Formatted email string + alert metadata |

### `build_weekly_email` output structure

The weekly email contains these sections in order:

```
Subject: Weekly MPF Portfolio Update [ACTION REQUIRED]?

1. Performance Summary
   portfolio_ytd vs benchmark_ytd vs target_return
   +/- difference columns

2. Alert Banner (severity based on conditions)
   ✅ On Track          — beats benchmark AND meets target
   ⚠️  Benchmark Alert  — below HSI only
   ⚠️  Target Alert     — below 20% target only
   🚨 URGENT            — below both

3. Recommended Reallocation
   • Fund Name: XX.X%  (per fund, 2%–40% bounds)

4. Optimization Rationale
   • Fund Name: [1-2 sentence explanation]
     covering: role, weight rationale, performance context

5. Forecasted Return Comparison (per HKD 100 invested)
                    Current Portfolio   New Portfolio   Difference
   Annual return  :     XX.X%              XX.X%         +X.X%
   3-Year cumul.  :     XX.X%              XX.X%
   3-Year value   :     HKD XXX.XX         HKD XXX.XX    +XX.XX
   5-Year cumul.  :     XX.X%              XX.X%
   5-Year value   :     HKD XXX.XX         HKD XXX.XX    +XX.XX

6. Next Steps
   Instructions to submit switch via MPF trustee portal
```

### Key constants

| Constant | Value | Purpose |
|---|---|---|
| `_INVESTOR_TARGET_RETURN` | `20.0` | Overall portfolio annual return target (%) |
| `_BENCHMARK` | HSI 19,845.32 / YTD 5.6% | Performance benchmark |
| `_PORTFOLIO` | 8 funds | Current holdings with allocation % and return history |
| `_FUND_UNIVERSE` | 8 funds | Same funds as optimisation candidates |
| `_MAX_RETRIES` | `3` | API retry attempts on transient errors |
| `_RETRY_BACKOFF_BASE` | `2.0s` | Base for exponential backoff (doubles each retry) |
| Per-fund bounds | `(0.02, 0.40)` | 2%–40% weight range per fund in optimised allocation |
| Bond floor | `0.05` | Minimum 5% in bond fund(s) |
| Risk-free rate | `4.0%` | HK approx., used for Sharpe ratio |

### Annualised return formula

3-year cumulative returns are converted to annualised figures using the compound formula:

```
annualised = ((1 + cumulative/100)^(1/years) - 1) * 100
```

Applied to 5 of the 8 funds that have 3yr history. The remaining 3 use 1yr return directly.

### API resilience (`_call_api_with_retry`)

```
Retry conditions:
  APIConnectionError  → always retry (up to 3x)
  APITimeoutError     → always retry (up to 3x)
  APIStatusError 429  → rate limited, retry with backoff
  APIStatusError 529  → overloaded, retry with backoff
  Other APIStatusError → raise immediately

Backoff: 2^attempt seconds (1s, 2s, 4s)
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
RootLayout (layout.tsx)       ← arrow function, export default
├── <Header />                ← nav bar + "가입하기" CTA button
├── <main>
│   └── <Home />              ← page.tsx, arrow function, export default
└── <Footer />                ← footer + "문의하기" CTA button
```

### Conventions (from CLAUDE.md)

- All React components **must** be arrow functions: `const Foo = () => { ... }`
- All major CTA buttons **must** use these exact Tailwind classes:
  `bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-md shadow-md`
