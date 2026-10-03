# Spendwise — Expense and Budget Manager

A responsive expense and budget website built with vanilla JavaScript, HTML/CSS, FastAPI, SQLAlchemy, and SQLite.

## Run locally

From the repository root (`C:\fastapi-class\venv`), activate the environment if it is not already active, then install the app dependencies and start FastAPI:

```powershell
.\Scripts\Activate.ps1
python -m pip install -r .\group_pro\requirements.txt
uvicorn group_pro.main:app --reload
```

Open <http://127.0.0.1:8000>. FastAPI creates `expenses.db` and seeds starter categories on first launch. The API reference is at <http://127.0.0.1:8000/docs>.

## What is included

- **Expenses:** list, add, edit, details, delete, validation, category assignment, and search.
- **Budgets:** create or update a category budget for a month and year; view spent and remaining amounts.
- **Categories:** shared category records used by expenses, budgets, and reports.
- **Insights:** monthly dashboard, year reports, and search/category/month/year filters.
- **Reports:** monthly expenditure chart plus a five-year annual spending graph, both based on saved expenses.
- **Display:** Indian rupee formatting and a light/dark theme switch that remembers your preference.
- **Budget Guard:** adding or editing an expense checks the matching category/month/year budget. The UI shows an over-budget warning and asks before saving; the API requires an explicit `confirm_over_budget` flag to proceed.

The three-table SQLite schema is also documented in `schema.sql`. SQLAlchemy creates the tables when the app starts.
