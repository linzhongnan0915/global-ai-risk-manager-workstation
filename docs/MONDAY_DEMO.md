# Monday Demo — Risk Manager Workstation

## Before the meeting (10 minutes)

```powershell
cd D:\Global_Ai\risk_manager_platform
python scripts\refresh_platform.py
python scripts\run_workstation_server.py --refresh-on-start
```

Open: `http://127.0.0.1:8765/dashboard/index.html`

Click **Refresh Live Data** once to pull latest yfinance market + news.

## 5-minute demo script

1. **Portfolio Command Center** — Friday PnL, contributors/detractors, portfolio chart, **factor exposure bar chart**, **news risk summary**, **recommendations**.
2. **Strategy Monitor** — click any allocated row → full stats in drawer (Sharpe, vol, DD, walk-forward, positions).
3. **Risk Factors & Exposure** — factor bar chart + matrix + limit breaches + scenario shocks.
4. **Market & Macro Monitor** — live market table + news feed with risk interpretation.
5. **Allocation & Rebalance** — edit weight → Simulate → factor before→after, cash sleeve, hard breach blocks approval.
6. **Daily Report** — Generate + export JSON.

## One-line pitch

> Multi-strategy risk workstation with **live yfinance market/news overlay**, transparent **factor exposure**, news-aware **recommendations**, and tested rebalance simulation — human approval required, no auto execution.

## Honest limitations (if asked)

- Strategy returns are ETF-proxy literature backtests, not boss live NAV feeds yet.
- Factor model is transparent proxy, not licensed Barra.
- News comes from yfinance/RSS-style feeds unless `RMP_NEWS_API_URL` is configured.
