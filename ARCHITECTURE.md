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
┌─────────────────────────────────────────────────────────┐
│                      __main__                           │
│  --scheduler │ --monthly │ --remind │ (default)         │
└────────┬─────────────────────────────┬──────────────────┘
         │                             │
         ▼                             ▼
  start_scheduler()             run_monthly_job()
  (daily cron loop)          send_fund_update_request()
         │                      run_agent(send_result=True)
         └──────────────┬────────────────────────────────┘
                        │
                        ▼
                  run_agent()
                        │
                        ▼
            ┌─────────────────────┐
            │  _call_api_with_    │  ← exponential backoff retry
            │  retry()            │    (429, 529, timeout, connection)
            └────────┬────────────┘
                     │  Anthropic Messages API
                     ▼
            ┌─────────────────────┐
            │   Claude Opus 4.6   │
            │   (agent loop)      │
            └────────┬────────────┘
                     │  tool_use blocks
                     ▼
            ┌─────────────────────┐
            │  dispatch_tool()    │
            └────────┬────────────┘
                     │
        ┌────────────┼─────────────────────┐
        ▼            ▼                     ▼
get_portfolio_  get_fund_universe   get_benchmark_state
    state()          ()                    ()
        │
        └────────────┬─────────────────────┐
                     ▼                     ▼
           optimize_allocation()   build_weekly_email()
           (Markowitz MVO,         (formats alert email,
            SLSQP solver)          returns JSON result)
                                          │
                                          ▼
                                   send_email()   ← SMTP
```

### Agent loop

The agent runs a standard tool-use loop:

1. Send `user_prompt` to Claude with the `TOOLS` schema
2. Claude responds with `tool_use` blocks
3. Each tool call is dispatched to the corresponding Python function
4. Results are fed back as `tool_result` blocks
5. Loop continues until `stop_reason != "tool_use"`
6. On completion, if `send_result=True` and `build_weekly_email` was called, the formatted email is sent via SMTP

### Data flow

```
_PORTFOLIO (static dict)
    │
    ├─► tool_get_portfolio_state()
    │       └─► weighted 1yr return + holdings JSON
    │
_FUND_UNIVERSE (static dict)
    │
    ├─► tool_get_fund_universe()
    │       └─► candidate funds for optimisation
    │
    └─► tool_optimize_allocation()
            ├─► expected returns array
            ├─► volatility estimates (from risk rating)
            ├─► heuristic correlation matrix (asset-class based)
            ├─► covariance matrix
            └─► SLSQP minimise variance subject to:
                    • weights sum to 1
                    • weighted return ≥ target
                    • bond allocation ≥ 5 %
                    • 2 % ≤ each weight ≤ 40 %
```

### Key constants

| Constant | Purpose |
|---|---|
| `_PORTFOLIO` | 8 current holdings with allocation %, return history |
| `_FUND_UNIVERSE` | Same 8 funds as optimisation candidates |
| `_BENCHMARK` | HSI level and YTD return |
| `_INVESTOR_TARGET_RETURN` | 8.0% p.a. target |
| `_MAX_RETRIES` | 3 API retry attempts |
| `_RETRY_BACKOFF_BASE` | 2.0s base for exponential backoff |

### Annualised return formula

3-year cumulative returns are converted to annualised figures using the compound formula:

```
annualised = ((1 + cumulative/100)^(1/years) - 1) * 100
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
RootLayout (layout.tsx)
├── <Header />          ← nav bar + "가입하기" CTA button
├── <main>
│   └── <Home />        ← page.tsx (landing content)
└── <Footer />          ← footer + "문의하기" CTA button
```

### Conventions (from CLAUDE.md)

- All React components are arrow functions (`const Foo = () => { ... }`)
- CTA buttons must use: `bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-md shadow-md`
