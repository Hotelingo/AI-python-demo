# Apex open invoice analysis

A simple finance teaching demo: choose cleaned invoice, payment and quarantine CSVs, choose an as-of date, and let a Python function calculate open balances. The public site includes a small fictional sample; no project data is committed here.

## Deploy on Vercel

Import this GitHub repository in Vercel. Select the default settings (Framework Preset: Other; root directory: repository root), and deploy. `index.html` is the frontend and `api/analyze.py` is a Python serverless function. No environment variables or third-party packages are required. Vercel's Python runtime must be available to the project.

## Use

Choose `invoices_clean.csv`, `payments_clean.csv`, `invoices_quarantine.csv`, and `payments_quarantine.csv` from the same cleaning run. Header-only quarantine files are valid. Set the as-of date and select Run analysis; download the detail if needed. The original local cleaning script is under `scripts/`; it is not run by the website. The desktop script is also included for reference; paths may need adjustment.

## Rules and limitations

Payments dated up to the selected cutoff are summed per invoice after checking vendor and currency. Age is calendar days since invoice date. More than 30 means 31 days or more; without due dates it is not an overdue measure. Credit notes and negative balances are shown separately, without automatic allocation. Quarantined rows and unlinked or mismatched payments require review. No ledger reconciliation, data persistence, user authentication, or completeness checks are provided. Changing dates does not guarantee a complete historical population; obtain complete data and confirm cutoff and credit treatment. Uploads are sent to Vercel for in-memory processing and are not stored by the app. Use only authorized non-sensitive demo data on a public deployment.

## Charts

Optionally upload `vendors_clean.csv` for supplier names. Otherwise charts show vendor IDs. For each selected currency, the app shows aging buckets (0–30, 31–60, 61–90, 91–120, 121+ days) and the top 10 suppliers by outstanding positive invoice balance, with invoice counts. Credits, overpayments, unmatched or mismatched records and quarantined rows are excluded from the chart totals and must be reviewed separately. The source is accounts payable, so the ranking is suppliers, not customers. Aging is based on invoice date, not due date.
