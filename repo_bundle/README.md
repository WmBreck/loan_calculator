# Shylock Online — Private Loan Servicing (MVP)

Streamlit + Supabase app to track irregular loan payments, allocate interest/fees/principal, and export clean statements.

## Structure
```
app/loan_app.py         # Streamlit app (with responsive header)
assets/ShylockLogo.png  # Brand logo (replace with your real logo)
sql/migrations.sql      # Idempotent database patches for Supabase
docs/prd.md             # Detailed Product Requirements Document
.streamlit/secrets.toml # (create locally from example below)
requirements.txt        # Python deps
.gitignore              # Common ignores
LICENSE                 # MIT (adjust if needed)
```

## Local Development

1) Create a virtual environment (optional but recommended)
```bash
python3 -m venv .venv && source .venv/bin/activate
```

2) Install dependencies
```bash
pip install -r requirements.txt
```

3) Configure Streamlit secrets
Create `.streamlit/secrets.toml` with:
```toml
[supabase]
url = "https://YOUR-PROJECT.supabase.co"
anon_key = "YOUR-ANON-KEY"
```

4) Apply database migrations
Open Supabase SQL editor, paste contents of `sql/migrations.sql`, and run.

5) Run
```bash
streamlit run app/loan_app.py
```

## Deploy ideas
- Streamlit Community/Cloud for quick MVP hosting.
- Later: wrap with a minimal FastAPI backend or move to a Next.js + Supabase stack for mobile wrappers (Capacitor/React Native).

## GitHub — First Push

```bash
git init
git add .
git commit -m "Shylock Online MVP: Streamlit + Supabase + header"
git branch -M main
# Create a new empty repo on GitHub first, then:
git remote add origin https://github.com/YOUR-USER/shylock-online.git
git push -u origin main
```

---

### Verification
Use these to verify integrity after cloning:
```bash
wc -l app/loan_app.py
shasum -a 256 app/loan_app.py
```
(The hash you got from the previous step will confirm the file.)

---

**License:** MIT (see LICENSE)
