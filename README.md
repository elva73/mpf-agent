# MPF Portfolio Intelligence System

An AI-powered Hong Kong MPF (Mandatory Provident Fund) portfolio monitoring and optimisation agent, paired with a Next.js landing page.

---

## Projects

| Directory | Description |
|---|---|
| `mpf_agent.py` | Python AI agent — portfolio analysis, MVO optimisation, email alerts |
| `my-next-app/` | Next.js 14 landing page (TypeScript + Tailwind CSS) |

---

## MPF Agent (`mpf_agent.py`)

### What it does

1. Fetches the investor's current portfolio holdings and performance
2. Compares trailing 1-year returns against the investor's target and the Hang Seng Index benchmark
3. Runs mean-variance optimisation (Markowitz, SLSQP) to recommend a reallocation
4. Drafts and optionally sends a weekly email alert with performance summary and recommended weights

### Requirements

```
pip install anthropic numpy pandas scipy schedule
```

Set the following environment variables:

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key (required) |
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

# Send fund-sheet update reminder email only
python mpf_agent.py --remind

# Run full monthly job (reminder + analysis + result email)
# Assumes _PORTFOLIO data is already updated for the current month
python mpf_agent.py --monthly

# Start long-running scheduler (fires on the 1st of each month at 08:00)
python mpf_agent.py --scheduler
```

### Updating fund data

The portfolio data is stored as constants in `mpf_agent.py`. Update `_PORTFOLIO`, `_FUND_UNIVERSE`, and `_BENCHMARK` each month with figures from your MPF provider's fund sheet, then re-run.

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
