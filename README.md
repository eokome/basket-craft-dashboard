# Basket Craft — Merchandising Dashboard

**Live app:** https://eokome-basket-craft-dashboard-app-6pxlmj.streamlit.app/

Streamlit dashboard backed by the Basket Craft Snowflake mart. Built for Maya, Head of Merchandising.

## Sections

- **KPI Scorecards** — total revenue, orders, average order value, and items sold with month-over-month delta
- **Revenue Trend** — monthly line chart with a sidebar date filter
- **Top Products by Revenue** — bar chart sorted descending, respects date filter
- **Bundle Finder** — pick a product, see what gets bought with it most often, download as CSV

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # fill in your Snowflake credentials
.venv/bin/streamlit run app.py
```
