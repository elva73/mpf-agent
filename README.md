# MPF Portfolio Intelligence System

An AI-powered Hong Kong MPF (Mandatory Provident Fund) portfolio monitoring and optimisation agent, paired with a Next.js landing page.

---

## Projects

| Directory | Description |
|---|---|
| `mpf_agent.py` | Python AI agent — portfolio analysis, MVO optimisation, email alerts |
| `my-next-app/` | Next.js 16 landing page (TypeScript + Tailwind CSS) |
| `test_email.py` | Local test script — generates a full email preview without the Claude API |

---

## MPF Agent (`mpf_agent.py`)

### What it does

1. Fetches the investor's current 8-fund MPF portfolio holdings and trailing 1-year performance
2. Compares performance against a **20% p.a. overall portfolio target** and the Hang Seng Index benchmark
3. Runs mean-variance optimisation (Markowitz, SLSQP) to recommend a reallocation across 8 candidate funds
4. Generates an **Optimization Rationale** — a single portfolio-level paragraph summarising expected return, Sharpe ratio, volatility, diversification breadth, and bond protection
5. Computes **3-year and 5-year forecasted return comparison** between the current and new portfolio (cumulative % and HKD future value per HKD 100 invested)
6. Drafts and optionally sends a weekly email alert with the full analysis

### Current Portfolio (8 funds)

| Fund | Asset Class | Risk | Allocation |
|---|---|---|---|
| Growth Fund | Mixed / Growth | High | 18.01% |
| Global Bond Fund | Bond – Global | Low to Medium | 15.16% |
| Hong Kong and Chinese Equity Fund | Equity – HK/China | High | 14.85% |
| European Equity Fund | Equity – Europe | Medium | 14.68% |
| Chinese Equity Fund | Equity – China | High | 11.84% |
| North American Equity Fund | Equity – North America | Medium | 10.89% |
| Hang Seng Index Tracking Fund | Equity – HK (Index) | Medium | 7.77% |
| Asia Pacific Equity Fund | Equity – APAC | Medium | 6.80% |

### Key settings

| Constant | Value | Description |
|---|---|---|
| `_INVESTOR_TARGET_RETURN` | `20.0%` | Overall portfolio annual return target |
| `_BENCHMARK` | HSI @ 19,845.32 | YTD return 5.6% |
| Per-fund bounds | 2%–40% | Min/max weight per fund in optimised allocation |
| Bond allocation floor | ≥ 5% | Minimum bond exposure for downside protection |
| Risk-free rate | 4.0% | Used for Sharpe ratio calculation (HK approx.) |

### Requirements

```
pip install anthropic numpy pandas scipy schedule
```

Set the following environment variables:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key (required for live agent) |
| `EMAIL_SMTP_HOST` | SMTP host (default: `smtp.gmail.com`) |
| `EMAIL_SMTP_PORT` | SMTP port (default: `587`) |
| `EMAIL_USERNAME` | SMTP login username |
| `EMAIL_PASSWORD` | SMTP login password |
| `EMAIL_SENDER` | From address |
| `EMAIL_RECIPIENT` | To address |

### Usage

```bash
# Run once (analysis only, no email)
python mpf_agent.py

# Send fund-sheet update reminder email only (no analysis)
python mpf_agent.py --remind

# Run full monthly job (reminder + analysis + result email)
# Assumes _PORTFOLIO data is already updated for the current month
python mpf_agent.py --monthly

# Start long-running scheduler (fires on the 1st of each month at 08:00)
python mpf_agent.py --scheduler
```

### Testing without the Claude API

```bash
python test_email.py
```

Calls `tool_optimize_allocation()` and `tool_build_weekly_email()` directly with real portfolio data. No `ANTHROPIC_API_KEY` required. Prints the full formatted email body and alert metadata to stdout.

### Email output sections

Each weekly email contains these 6 sections:

1. **Performance Summary** — portfolio return vs HSI benchmark vs 20% target, with +/- difference
2. **Alert Banner** — severity driven by two conditions:

   | Condition | Alert |
   |---|---|
   | Beats benchmark AND meets target | ✅ On Track |
   | Below HSI only | ⚠️ Benchmark Underperformance |
   | Below 20% target only | ⚠️ Target Return Not Met |
   | Below both | 🚨 URGENT ACTION REQUIRED |

3. **Recommended Reallocation** — optimised fund weights (2%–40% per fund)
4. **Optimization Rationale** — single paragraph covering: expected annual return and improvement vs current, 3-year cumulative projection, Sharpe ratio, annualised volatility, number of funds and asset classes, and bond exposure fund name and percentage
5. **Forecasted Return Comparison** — side-by-side table (per HKD 100 invested):
   - Annual return: current % vs new % vs difference
   - 3-year: cumulative %, HKD future value, gain vs current
   - 5-year: cumulative %, HKD future value, gain vs current
6. **Next Steps** — instructions to submit switch via MPF trustee portal (3–5 business days)

### Sample Optimization Rationale output

```
─── Optimization Rationale ────────────────────────────
  This rebalanced allocation targets an expected annual return of ~20.0%
  (+5.3% vs current 14.7%), projecting a cumulative return of ~72.8% over
  3 years, pushing toward the 20.0% overall portfolio target. The optimiser
  achieves a Sharpe ratio of 1.78 at annualised volatility of 9.0%,
  distributing capital across 8 funds and 8 asset classes for superior
  diversification. Bond exposure of 9.7% (Global Bond Fund) provides
  downside protection and cushions against equity market drawdowns.
```

### Updating fund data

Update `_PORTFOLIO`, `_FUND_UNIVERSE`, and `_BENCHMARK` in `mpf_agent.py` each month with the latest figures from your MPF provider's fund sheet, then re-run.

Fields to update per fund:
- `allocation_pct`, `return_1m_pct`, `return_3m_pct`, `return_6m_pct`
- `return_1yr_pct`, `return_3yr_pct`, `annualised_return_pct`
- `_BENCHMARK` — `ytd_return_pct` and `level`

---

## Landing Page (`my-next-app/`)

### Requirements

- Node.js 18+
- npm

### Usage

```bash
cd my-next-app
npm install
npm run dev      # development server at http://localhost:3000
npm run build    # production build
npm run start    # serve production build
npm run lint     # ESLint
```

---

## Environment Setup (quick start)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export EMAIL_SMTP_HOST="smtp.gmail.com"
export EMAIL_USERNAME="you@gmail.com"
export EMAIL_PASSWORD="your-app-password"
export EMAIL_SENDER="you@gmail.com"
export EMAIL_RECIPIENT="investor@example.com"

python mpf_agent.py
```
