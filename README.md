# Shylock Loan Servicing App (MVP)

This bundle contains:
- **loan_app.py** — Streamlit app (Supabase + responsive header + late fees/penalty interest)
- **prd.md** — Detailed Product Requirements Document
- **migrations.sql** — Safe schema patches for Supabase
- **ShylockLogo.png** — Placeholder logo (replace with your own)

## Setup
1. In Supabase, add secrets to Streamlit:
   ```toml
   [supabase]
   url = "https://YOUR-PROJECT.supabase.co"
   anon_key = "YOUR-ANON-KEY"
   ```
2. Run migrations: open Supabase SQL editor, paste and run `migrations.sql`.
3. Install deps:
   ```bash
   pip install streamlit supabase matplotlib pandas
   ```
4. Start:
   ```bash
   streamlit run loan_app.py
   ```

## Notes
- Place your real `ShylockLogo.png` next to `loan_app.py` for the header.
- Colors: **Shylock** (#00B050), **Online** (#E32636) — matched to your logo.
