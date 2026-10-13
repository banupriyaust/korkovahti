# Korkovahti: Euribor, made clear

**Live site: [korkovahti.banupriyaust.workers.dev](https://korkovahti.banupriyaust.workers.dev)**

An end-to-end data product that turns public ECB data into answers a home-loan
borrower can act on: where Euribor has been, where it stands, what markets
expect next, and what that means for the monthly payment.

*Korkovahti* is Finnish for "interest-rate watch". The primary audience is
Finnish borrowers, most of whose loans follow the 12-month Euribor. Spain,
Portugal, Italy and Austria are supported with their own conventions.

## Why I built it

Sites that publish Euribor show the number. They don't answer the questions a
borrower actually has:

- My rate resets in April. What will my payment be?
- Is the market expecting rates to rise or fall before then?
- I'm taking a new loan. How do 3, 6 and 12-month reference rates compare?
- How much uncertainty is there around any of this?

As a data analyst I wanted a project that goes past a dashboard: source the
data, model it, state the uncertainty plainly, and deliver it to people who are
not analysts.

## What it delivers

| Section | Question it answers | How |
|---|---|---|
| **Rates** | Where does each maturity stand? | Latest ECB monthly averages for 1, 3, 6 and 12 months, with year-on-year change |
| **History** | How did we get here? | 27 years of monthly data against the ECB deposit rate, with range filters and a yearly table |
| **Outlook** | What are markets pricing in? | A five-year market-implied path with an empirical uncertainty band |
| **Your loan** | What happens to my payment? | Annuity recalculation at the next reset, in three years, and under a 6 % stress test |
| **Ask** | What does this mean for me? | An AI assistant grounded in the page's own figures and the visitor's loan inputs |

### What the data says (build of 13 October 2026)

- The 12-month Euribor averaged **3.25 %** in September 2026, **1.08 points
  higher** than a year earlier, after two ECB rate rises in 2026.
- Since 1999 it has ranged from **5.39 %** (July 2008) to **-0.51 %**
  (January 2021), and was **negative for 74 consecutive months** (February 2016
  to March 2022).
- Markets imply roughly **3.55 %** in one year. Historically, half of all
  one-year moves fell outside a band of about -0.3 to +0.6 points around the
  expected path, which is why the page shows a range and not a single number.
- For a EUR 180,000 loan with 20 years left and a 0.75 % margin, that path
  means about **EUR 69 more per month** at an April 2027 reset.

## How it works

```mermaid
flowchart LR
    A[ECB Data Portal API] -->|monthly Euribor, deposit rate, yield curve| B[build.py]
    B -->|validated JSON embedded in page| C[public/index.html]
    D[GitHub Actions, weekdays 07:30 UTC] --> B
    C --> E[Cloudflare Worker]
    E -->|static site| F[Visitor]
    F -->|question + page figures| E
    E -->|Workers AI| G[Open LLM]
```

### Data pipeline (`build.py`)

- Pulls five datasets from the ECB's SDMX REST API: four Euribor maturities
  (monthly, from January 1999), the deposit facility rate, and the daily
  Svensson yield-curve parameters.
- Validates before publishing: every series must start in the same month and
  cover the same periods, and the calibration month must have enough curve
  observations. A failed check stops the build so bad data never reaches the
  site.
- Runs on a schedule in GitHub Actions and commits only when the data changed.
- Uses the Python standard library only. No dependencies to install.

### Analysis

**Market-implied path.** Forward rates are derived from the ECB's AAA
government-bond yield curve using the Svensson model:

```
f(t, m) = [ s(t+m)·(t+m) − s(t)·t ] / m
```

where `s` is the continuously compounded spot rate. Government-bond yields sit
below Euribor, so each maturity is shifted by the spread between the two,
calibrated over the latest full month (0.33 points for the 12-month rate).

**"Today" estimate.** The same spread applied to today's curve gives a current
estimate between official monthly prints. Checked against the real fixing of
12 October 2026 it was within 0.07 points.

**Uncertainty band.** For each horizon from 1 to 60 months, the band is the
interquartile range of every historical move over that horizon since 1999,
centred on the market path and smoothed across neighbouring horizons. It is
empirical and assumes no distribution.

**Loan maths.** Standard annuity formula, with the payment recalculated at
each reset from the remaining balance and remaining term. The stress test uses
the Finnish FSA's affordability guideline of 6 % over at most 25 years.

### Visualisation

Charts are hand-written SVG with no charting library, which keeps the whole
page at about 55 KB. Design decisions:

- One y-axis per chart, never dual axes.
- A colour-blind-safe two-colour palette, with a legend and a table view so
  colour is never the only cue.
- Hover crosshair and tooltips on every chart.
- Light and dark themes, and a layout that works on a phone.

### AI assistant

Each question is sent with a compact summary of the page's figures and the
visitor's loan inputs, plus fixed rules: use only those numbers, describe the
outlook as market pricing and not a forecast, and give no financial advice.
The model has no memory and learns nothing from visitors. It runs on
Cloudflare Workers AI's free allowance, so visitors need no account.

## Decisions worth noting

- **Data licensing.** Daily Euribor fixings belong to EMMI and need a licence
  to redistribute. The project uses only ECB-published data, which is free to
  reuse, and derives the current level instead of republishing fixings.
- **Honest uncertainty.** The outlook is labelled as market pricing, shown with
  a range, and the page states that half of real outcomes fell outside it.
- **Known bias.** Bond forwards include a term premium, so the path beyond two
  or three years tends to sit above what investors truly expect. The page says
  so.
- **Zero running cost.** Free hosting, free data, free AI tier with a hard
  daily cap, so nothing can generate a bill.

## Skills this project demonstrates

| Area | Evidence |
|---|---|
| Data sourcing and APIs | ECB SDMX REST API, five datasets, CSV parsing |
| ETL and automation | Scheduled pipeline with validation gates and change-only commits |
| Time-series analysis | 27 years of monthly rates, horizon-based change distributions |
| Financial modelling | Svensson curve, forward rates, spread calibration, annuity schedules |
| Data visualisation | Custom SVG charts, accessible palette, responsive and themed |
| Communicating to non-analysts | Plain-language findings, explicit uncertainty, country-specific context |
| Data governance | Licensing review that shaped the data model |
| Product delivery | Serverless hosting, API backend, LLM integration with guardrails |

## Repository

| File | Purpose |
|---|---|
| `template.html` | The page: layout, charts, calculator and chat client |
| `build.py` | Data pipeline: fetches ECB data and writes `public/index.html` |
| `public/index.html` | The built site |
| `worker.js` | Cloudflare Worker: serves the site and answers `/api/ask` |
| `wrangler.toml` | Cloudflare settings, including the AI model |
| `.github/workflows/refresh.yml` | Scheduled data refresh |

## Run it

```bash
python build.py
python -m http.server 8000 --directory public
```

Then open `http://localhost:8000`. Everything works locally except the chat,
which needs the Cloudflare Worker.

## Deploy (free)

1. In Cloudflare, open **Workers & Pages**, choose **Create**, then
   **Import a repository**, and pick this repository. Leave the build command
   empty and keep the deploy command as `npx wrangler deploy`.
2. In this repository, open **Actions** and enable workflows so the data
   refreshes each weekday.

Workers AI gives 10,000 "neurons" a day for free. When they run out the chat
pauses until midnight UTC, and nothing is billed on the free plan. If the chat
stops answering after a model is retired, change `MODEL` in `wrangler.toml`.

## Limitations and next steps

- The "today" figure is an estimate, not the official fixing.
- The outlook comes from government-bond forwards, a proxy for Euribor futures.
- The chat has no per-visitor rate limit yet.
- Planned: back-test the market-implied path against realised rates,
  fixed-instalment loans, Finnish-language version.

## Data sources

- [ECB Data Portal](https://data.ecb.europa.eu): Euribor monthly averages
  (`FM` dataset), deposit facility rate, euro-area yield curve (`YC` dataset).
- Euribor is administered by the European Money Markets Institute.

## About

Built by **Banupriya Selvaraj**, data analyst and BI developer.
[LinkedIn](https://www.linkedin.com/in/banupriya-selvaraj) ·
[GitHub](https://github.com/banupriyaust)

Developed with Claude Code as a pair-programming assistant.

This project is for information only and is not financial advice.

© 2026 Banupriya Selvaraj. All rights reserved.
