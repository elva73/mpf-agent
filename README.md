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
4. Generates an **Optimization Rationale** — a single portfolio-level paragraph summarising expected return, Sharpe ratio, volatility, diversification breadth, and bond protection; also builds a **Current Portfolio Holdings table** (all 8 funds with allocation %, 1yr return %, risk level, and inline bar chart) and an **ASCII Round Chart** (proportional bar using 8 distinct block symbols across 60 characters)
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

Calls `tool_optimize_allocation()` and `tool_build_weekly_email()` directly with real portfolio data. No `ANTHROPIC_API_KEY` required. Outputs the complete formatted email body directly to stdout — no debug lines, no separators.

### Email output sections

Each weekly email contains these sections in order:

1. **Performance Summary** — portfolio return vs HSI benchmark vs 20% target, with +/- difference
2. **Alert Banner** — severity driven by two conditions:

   | Condition | Alert |
   |---|---|
   | Beats benchmark AND meets target | ✅ On Track |
   | Below HSI only | ⚠️ Benchmark Underperformance |
   | Below 20% target only | ⚠️ Target Return Not Met |
   | Below both | 🚨 URGENT ACTION REQUIRED |

3. **Optimisation Stats** — solver status, current return vs target vs gap, new optimised return / volatility / Sharpe
4. **Current Portfolio Holdings** — table showing all 8 funds: fund name, allocation %, 1yr return %, risk level, and an inline bar chart where each `█` block represents approximately 2% allocation
5. **Current Allocation Round Chart** — ASCII proportional bar chart using 8 distinct block symbols (`▓░▒■□▪▫◆`), total width 60 characters, with a legend below showing symbol, fund name, and allocation %
6. **Recommended Reallocation Highlights** — bullet list with `↑`/`↓` arrows, new %, "was X%", and 1yr return context per fund
7. **Optimization Rationale** — single auto-generated paragraph: expected return (annual + 3yr cumulative), target range, Sharpe ratio, volatility, asset class count, bond exposure
8. **Forecast Summaries** — bullet-point 5-year and 3-year HKD future value per HKD 100 invested, with gain vs current
9. **Next Steps** — instructions to submit switch via MPF trustee portal (3–5 business days)

### Sample email output

```
Subject: Weekly MPF Portfolio Update [ACTION REQUIRED]

Dear Investor,

Here is your weekly MPF portfolio review.

─── Performance Summary ───────────────────────────────
  Portfolio return     : 14.7%
  Hang Seng Index YTD  : 5.6%
  Your target return   : 20.0%
  vs Benchmark         : +9.1%
  vs Target            : -5.3%

─── ⚠️  ALERT: Target Return Not Met ───────────────────────
  ✗ Portfolio return (14.7%) is BELOW your target return (20.0%)

Your portfolio is not meeting your target. Reallocation toward the
recommended weights is advised.

Optimisation stats:
  * Solver: ✅ Converged successfully
  * Current portfolio return: 14.7% | Target: 20.0% | Gap: -5.3%
  * New optimised return: 20.0% | Volatility: 8.97% | Sharpe: 1.784

─── Current Portfolio Holdings ────────────────────────
  Fund                                        Alloc  1yr Rtn  Risk            Chart (each █ ≈ 2%)
  ────────────────────────────────────────── ──────  ───────  ──────────────  ────────────────────
  Growth Fund                                 18.0%   +21.2%  High            █████████
  Global Bond Fund                            15.2%    +5.0%  Low to Medium   ███████
  Hong Kong and Chinese Equity Fund           14.8%   +13.1%  High            ███████
  European Equity Fund                        14.7%   +15.8%  Medium          ███████
  Chinese Equity Fund                         11.8%   +10.3%  High            █████
  North American Equity Fund                  10.9%   +17.9%  Medium          █████
  Hang Seng Index Tracking Fund                7.8%    +9.8%  Medium          ███
  Asia Pacific Equity Fund                     6.8%   +27.9%  Medium          ███

─── Current Allocation — Round Chart ──────────────────
  ┌────────────────────────────────────────────────────────────┐
  │▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░▒▒▒▒▒▒▒▒▒■■■■■■■■■□□□□□□□▪▪▪▪▪▪▪▫▫▫▫▫◆◆◆│
  └────────────────────────────────────────────────────────────┘

  ▓ Growth Fund                                 18.0%
  ░ Global Bond Fund                            15.2%
  ▒ Hong Kong and Chinese Equity Fund           14.8%
  ■ European Equity Fund                        14.7%
  □ Chinese Equity Fund                         11.8%
  ▪ North American Equity Fund                  10.9%
  ▫ Hang Seng Index Tracking Fund                7.8%
  ◆ Asia Pacific Equity Fund                     6.8%

Recommended reallocation highlights:
  * ↓ Growth Fund: 2.0% (was 18.0%) — +21.2% 1yr return
  * ↓ Global Bond Fund: 9.7% (was 15.2%) — +5.0% 1yr return
  * ↓ Hong Kong and Chinese Equity Fund: 2.0% (was 14.8%) — +13.1% 1yr return
  * ↓ European Equity Fund: 13.9% (was 14.7%) — +15.8% 1yr return
  * ↓ Chinese Equity Fund: 2.0% (was 11.8%) — +10.3% 1yr return
  * ↑ North American Equity Fund: 28.4% (was 10.9%) — +17.9% 1yr return
  * ↓ Hang Seng Index Tracking Fund: 2.0% (was 7.8%) — +9.8% 1yr return
  * ↑ Asia Pacific Equity Fund: 40.0% (was 6.8%) — +27.9% 1yr return

Optimization Rationale: This rebalanced allocation drives an expected
return of ~20.0% per annum (~72.8% cumulative over 3 years), projecting
toward the 20.0–22% target. We achieve superior diversification across
8 asset classes and an improvement in a Sharpe ratio of 1.78, while
annualised volatility of 9.0% ensures downside risk remains within
tolerance. Bond exposure of 9.7% (Global Bond Fund) provides additional
downside protection against equity market drawdowns.

5-year forecast per HKD 100 invested:
  * Current portfolio → HKD 198.18 (annual: 14.7%)
  * New portfolio     → HKD 248.83 (+5.34% annual improvement)
  * Gain vs current   → +HKD 50.65

3-year forecast per HKD 100 invested:
  * Current portfolio → HKD 150.74
  * New portfolio     → HKD 172.80
  * Gain vs current   → +HKD 22.06

  * Forecast assumes constant annual return equal to trailing 1-year
    performance. Actual returns will vary with market conditions.

─── Next Steps ────────────────────────────────────────
1. Review the reallocation above PROMPTLY.
2. Log in to your MPF trustee portal to submit the switch instruction.
3. Allow 3–5 business days for the switch to take effect.
4. Your next weekly update will confirm the new allocation performance.

Kind regards,
MPF Portfolio Intelligence System
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
