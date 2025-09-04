# loan_app.py
import streamlit as st
st.set_page_config(page_title="Shylock — Private Loan Servicing", page_icon="💸", layout="centered")

from datetime import date, datetime as _dt
import base64, secrets
from pathlib import Path
import pandas as pd

from shylock_ledger import (
    compute_ledger, make_display, render_ledger, build_pdf_from_ledger, parse_us_date
)

# ---------------- Supabase ----------------
try:
    from supabase import create_client, Client
    _sb = st.secrets.get("supabase", {})
    SUPABASE_URL = _sb.get("url"); SUPABASE_ANON_KEY = _sb.get("anon_key")
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("Missing supabase.url or supabase.anon_key in Streamlit secrets.")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    SUPABASE_OK = True
except Exception as e:
    SUPABASE_OK = False; supabase = None
    st.error(f"Supabase init failed: {e}")

# ---------------- Style ----------------
def _inject_global_css():
    st.markdown(
        """
        <style>
          .block-container {max-width: 980px; margin: 0 auto;}
          [data-testid="stDataEditor"], [data-testid="stDataFrame"] {overflow: auto!important;}
          @media (min-width: 1000px) {
            [data-testid="stSidebar"] {min-width: 300px; max-width: 320px;}
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

def render_header(
    logo_path: str = "ShylockLogo.png",
    tagline: str = "The humane way to track private personal loans.",
    shylock_color: str = "#00B050", online_color: str = "#E32636",
):
    logo_b64 = ""
    p = Path(logo_path)
    if p.exists():
        try: logo_b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
        except Exception: logo_b64 = ""
    st.markdown(
        f"""
<style>
.shylock-header {{display:flex;align-items:center;justify-content:space-between;gap:1rem;width:100%;
  padding:.5rem 0 .75rem;border-bottom:1px solid rgba(0,0,0,.07);flex-wrap:wrap;}}
.shylock-wordmark {{display:flex;align-items:center;gap:1rem;flex:1 1 auto;min-width:280px;line-height:1;}}
.shylock-text {{font-family:"Georgia","Garamond","Times New Roman",serif;font-weight:700;letter-spacing:.5px;
  display:inline-flex;align-items:center;gap:.8rem;white-space:nowrap;}}
.shylock-text .shylock {{color:{shylock_color};font-size:clamp(32px,4vw,48px);}}
.shylock-text .online  {{color:{online_color}; font-size:clamp(32px,4vw,48px);}}
.shylock-logo {{display:inline-block;width:clamp(36px,4vw,52px);height:clamp(36px,4vw,52px);object-fit:contain;vertical-align:middle;}}
.shylock-tagline {{font-family:"Georgia","Garamond",serif;font-weight:500;font-size:clamp(12px,1.6vw,16px);color:rgba(0,0,0,.72);}}
@media (max-width:900px){{.shylock-header{{justify-content:center;}}
  .shylock-tagline{{width:100%;text-align:center;margin-top:.25rem;}}}}
</style>
<div class="shylock-header">
  <div class="shylock-wordmark">
    <div class="shylock-text">
      <span class="shylock">Shylock</span>
      {"<img class='shylock-logo' src='data:image/png;base64," + logo_b64 + "' alt='logo'/>" if logo_b64 else ""}
      <span class="online">Online</span>
    </div>
  </div>
  <div class="shylock-tagline">{tagline}</div>
</div>
""",
        unsafe_allow_html=True,
    )

# ---------------- Auth helpers ----------------
def get_session():
    if not SUPABASE_OK: return None
    try: return supabase.auth.get_session()
    except Exception: return None

def ensure_session_in_state():
    if not SUPABASE_OK: return
    if "session" not in st.session_state:
        sess = get_session()
        if sess and getattr(sess, "session", None):
            st.session_state["session"] = sess.session

def sign_out():
    if not SUPABASE_OK: return
    try:
        supabase.auth.sign_out()
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.success("✅ Signed out")
    except Exception as e:
        st.error(f"Sign out error: {e}")

def qp_get(name, default=None):
    return st.query_params.get(name, default)

def role_from_query() -> str | None:
    return st.session_state.get("role") or qp_get("role")

def borrower_token_from_query() -> str | None:
    return qp_get("token")

def set_role_in_url(role: str):
    st.session_state["role"] = role
    try: st.query_params["role"] = role
    except Exception: pass

# ---------------- DB access ----------------
def loans_for_lender(user_id: str):
    try:
        return supabase.table("loans").select("*").eq("lender_id", user_id).order("created_at").execute().data or []
    except Exception:
        return []

def loans_for_borrower_by_token(token: str):
    if not token: return []
    try:
        return supabase.table("loans").select("*").eq("borrower_token", token).limit(1).execute().data or []
    except Exception:
        return []

def loans_for_borrower_signed_in(user_id: str):
    try:
        supabase.table("loan_borrowers").select("loan_id").limit(1).execute()
        lb = supabase.table("loan_borrowers").select("loan_id").eq("user_id", user_id).execute().data or []
        ids = [r["loan_id"] for r in lb]
        if not ids: return []
        return supabase.table("loans").select("*").in_("id", ids).order("created_at").execute().data or []
    except Exception:
        return []

def payments_for_loan(loan_id: str) -> pd.DataFrame:
    try:
        rows = supabase.table("payments").select("*").eq("loan_id", loan_id).order("payment_date").execute().data or []
    except Exception:
        rows = []
    if not rows:
        return pd.DataFrame(columns=["payment_date", "amount"])
    df = pd.DataFrame(rows)
    df["payment_date"] = pd.to_datetime(df["payment_date"], errors="coerce").dt.date
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df[["payment_date", "amount"]].dropna()

def upsert_loan(loan: dict):
    return supabase.table("loans").upsert(loan, on_conflict="id").execute()

def delete_loan(loan_id: str):
    return supabase.table("loans").delete().eq("id", loan_id).execute()

def replace_payments(loan_id: str, df: pd.DataFrame):
    supabase.table("payments").delete().eq("loan_id", loan_id).execute()
    if df is None or df.empty: return
    payload = []
    for _, r in df.iterrows():
        try:
            dt = pd.to_datetime(r["payment_date"]).date().isoformat()
            amt = float(r["amount"])
            if amt <= 0: continue
            payload.append({"loan_id": loan_id, "payment_date": dt, "amount": amt})
        except Exception:
            continue
    if payload:
        supabase.table("payments").insert(payload).execute()

# ---------------- CSV clean ----------------
def clean_payments_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["payment_date", "amount"])
    out = df.copy()
    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
    if "date" in out.columns and "payment_date" not in out.columns:
        out = out.rename(columns={"date": "payment_date"})
    if "amount" not in out.columns:
        raise ValueError("Missing 'Amount' column")
    out["payment_date"] = pd.to_datetime(out["payment_date"], errors="coerce").dt.date
    amt = out["amount"].astype(str).str.strip()
    amt = (amt.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
               .str.replace(",", "", regex=False)
               .str.replace("$", "", regex=False)
               .str.replace("\u00A0", "", regex=False))
    out["amount"] = pd.to_numeric(amt, errors="coerce")
    out = out.dropna(subset=["payment_date", "amount"]).reset_index(drop=True)
    out = out[out["amount"] > 0]
    return out[["payment_date", "amount"]]

# ---------------- Views ----------------
def landing():
    render_header()
    st.title("Welcome")
    st.write("Track irregular payments, allocate interest/fees/principal correctly, and export clean statements.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("I’m a Lender (Manage Loans)", use_container_width=True):
            set_role_in_url("lender"); st.rerun()
    with c2:
        if st.button("I’m a Borrower (View Only)", use_container_width=True):
            set_role_in_url("borrower"); st.rerun()

    st.divider()
    st.subheader("Sign in / Sign up")
    with st.expander("Email & Password", expanded=True):
        email = st.text_input("Email"); pw = st.text_input("Password", type="password")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Sign Up", use_container_width=True):
                if not email or not pw:
                    st.error("Please enter both email and password.")
                else:
                    try:
                        supabase.auth.sign_up({
                            "email": email, "password": pw,
                            "options": {"email_redirect_to": "http://localhost:8501"}
                        })
                        st.success(f"Signup initiated. Check {email}.")
                    except Exception as e:
                        st.error(f"Signup error: {e}")
        with c2:
            if st.button("Sign In", use_container_width=True):
                if not email or not pw:
                    st.error("Please enter both email and password.")
                else:
                    try:
                        res = supabase.auth.sign_in_with_password({"email": email, "password": pw})
                        st.session_state["session"] = res.session
                        st.success(f"✅ Signed in as {email}"); st.rerun()
                    except Exception as e:
                        st.error(f"Sign in error: {e}")
        with c3:
            if st.button("Send Magic Link", use_container_width=True):
                if not email:
                    st.error("Enter your email first.")
                else:
                    try:
                        supabase.auth.sign_in_with_otp({"email": email, "options": {"email_redirect_to": "http://localhost:8501"}})
                        st.success(f"Magic link sent to {email}")
                    except Exception as e:
                        st.error(f"Magic link error: {e}")

def borrower_view_by_token(token: str):
    render_header()
    rows = loans_for_borrower_by_token(token)
    if not rows:
        st.error("Invalid or expired borrower link."); return
    loan = rows[0]
    st.title(f"📋 Loan Statement — {(loan.get('loan_name') or loan.get('name') or 'Loan')}")
    _common_loan_view(loan, read_only=True)

def borrower_view_signed_in(user_id: str):
    render_header(); rows = loans_for_borrower_signed_in(user_id)
    st.title("📋 Your Loans (Borrower)")
    if not rows:
        st.info("No loans are shared with this account."); return
    names = [f"{(r.get('loan_name') or r.get('name') or 'Loan')} — {r.get('borrower_name','(Borrower?)')}" for r in rows]
    idx = st.selectbox("Select loan", range(len(rows)), format_func=lambda i: names[i])
    _common_loan_view(rows[idx], read_only=True)

def lender_view(user_id: str):
    render_header()
    st.title("💸 Manage Loans & Statements")
    st.caption("One row per due date • Early payments apply to next due • Late fees capitalized at grace")

    try:
        prof = supabase.table("profiles").select("company_name").eq("id", user_id).single().execute()
        company_name = prof.data.get("company_name", "Your Company") if prof.data else "Your Company"
    except Exception:
        company_name = "Your Company"
    st.info(f"🏢 Managing loans for **{company_name}**")

    loans = loans_for_lender(user_id)

    a, b, c = st.columns([1.5,1,1])
    with a:
        if st.button("➕ New Loan"):
            try:
                upsert_loan({
                    "lender_id": user_id, "lender_name": company_name,
                    "loan_name": f"Loan {len(loans)+1}",
                    "principal": 100000.0, "origination_date": date.today().isoformat(),
                    "annual_rate": 5.0, "term_years": 30,
                    "borrower_name": "To be set", "borrower_email": "to_be_set@example.com",
                    "borrower_token": secrets.token_urlsafe(24),
                }); st.rerun()
            except Exception as e:
                st.error(f"Create loan failed: {e}")
    with b:
        if st.button("🔄 Refresh"): st.rerun()
    with c:
        if st.button("🚪 Sign out"): sign_out(); st.rerun()

    if not loans:
        st.info("No loans yet. Click **New Loan** to create one."); return

    show_ids = st.checkbox("Show loan IDs", value=False)
    sel = st.selectbox(
        "Select Loan",
        options=range(len(loans)),
        format_func=lambda i: f"{(loans[i].get('loan_name') or loans[i].get('name') or 'Loan')} — {loans[i].get('borrower_name','(Borrower?)')}" + (f" — {loans[i]['id'][:8]}" if show_ids else "")
    )
    loan = loans[sel]

    # -------- sidebar (edit) --------
    with st.sidebar:
        st.header("💰 Loan Terms")
        name = st.text_input("Loan Name", value=(loan.get("loan_name") or loan.get("name","")))
        borrower_name = st.text_input("Borrower Name", value=loan.get("borrower_name",""))
        principal = st.number_input("Original Principal ($)", min_value=0.0, value=float(loan.get("principal") or 0.0), step=1000.0, format="%.2f")

        orig_str = _dt.strftime(pd.to_datetime(loan.get("origination_date")).to_pydatetime(), "%m/%d/%Y") if loan.get("origination_date") else ""
        origination_date_val = parse_us_date(st.text_input("Origination Date (MM/DD/YYYY)", value=orig_str)) or (pd.to_datetime(loan.get("origination_date")).date() if loan.get("origination_date") else date.today())

        annual_rate_pct = st.number_input("Interest Rate (APR %)", min_value=0.0, value=float(loan.get("annual_rate") or 0.0), step=0.1, format="%.3f")
        term_years = st.number_input("Loan Term (years)", min_value=1, value=int(loan.get("term_years") or 30), step=1)

        st.divider(); st.subheader("Late Fee Rules")
        late_fee_type = st.selectbox("Late Fee Type", ["fixed","percent"], index=0 if loan.get("late_fee_type") in (None, "fixed") else 1)
        late_fee_amount = st.number_input("Late Fee Amount ($ or % of cycle interest)", min_value=0.0, value=float(loan.get("late_fee_amount") or 0.0), step=1.0, format="%.2f")
        grace_days = st.number_input("Grace Period (days)", min_value=0, value=int(loan.get("late_fee_days") or 4), step=1)

        with st.expander("Borrower link (read-only)", expanded=False):
            st.code(f"?role=borrower&token={loan.get('borrower_token')}", language="text")
            if st.button("Generate New Borrower Token"):
                loan["borrower_token"] = secrets.token_urlsafe(32); upsert_loan(loan); st.success("New borrower token generated.")

        st.markdown("### Actions")
        cA, cB = st.columns(2)
        with cA:
            if st.button("💾 Save Loan", use_container_width=True):
                loan.update({
                    "loan_name": name, "borrower_name": borrower_name, "principal": principal,
                    "origination_date": origination_date_val.isoformat(),
                    "annual_rate": annual_rate_pct, "term_years": int(term_years),
                    "late_fee_type": late_fee_type, "late_fee_amount": late_fee_amount,
                    "late_fee_days": int(grace_days),
                })
                try: upsert_loan(loan); st.success("Saved."); st.rerun()
                except Exception as e: st.error(f"Save failed: {e}")
        with cB:
            if st.button("🗑️ Delete Loan", use_container_width=True):
                try: delete_loan(loan["id"]); st.warning("Loan deleted."); st.rerun()
                except Exception as e: st.error(f"Delete failed: {e}")

    # Effective values (compute immediately without requiring Save)
    loan_effective = loan.copy()
    loan_effective.update({
        "loan_name": name, "borrower_name": borrower_name, "principal": principal,
        "origination_date": origination_date_val.isoformat(),
        "annual_rate": annual_rate_pct, "term_years": int(term_years),
        "late_fee_type": late_fee_type, "late_fee_amount": late_fee_amount,
        "late_fee_days": int(grace_days),
    })

    _common_loan_view(loan_effective, read_only=False)

# ---------------- Shared view ----------------
def _common_loan_view(loan_row: dict, read_only: bool):
    loan_id = loan_row["id"]
    payments_df = payments_for_loan(loan_id)

    st.subheader("Payments")
    st.caption("Upload CSV with columns: Date, Amount (or Payment Date, Amount). Positive amounts = payments.")

    if payments_df.empty:
        uploaded = st.file_uploader("Upload payments CSV (optional)", type=["csv"], disabled=read_only)
        if uploaded is not None and not read_only:
            try:
                tmp = pd.read_csv(uploaded, dtype=str, keep_default_na=False)
                cols_lower = [c.lower().strip() for c in tmp.columns]
                if "date" in cols_lower and "amount" in cols_lower:
                    tmp = tmp.rename(columns={tmp.columns[cols_lower.index("date")]: "payment_date",
                                              tmp.columns[cols_lower.index("amount")]: "amount"})
                elif "payment_date" in cols_lower and "amount" in cols_lower:
                    tmp = tmp.rename(columns={tmp.columns[cols_lower.index("payment_date")]: "payment_date",
                                              tmp.columns[cols_lower.index("amount")]: "amount"})
                else:
                    st.error("CSV must include columns: Date, Amount (or Payment Date, Amount)."); tmp = None
                if tmp is not None:
                    cleaned = clean_payments_df(tmp); replace_payments(loan_id, cleaned)
                    st.success(f"Imported {len(cleaned)} payments."); payments_df = payments_for_loan(loan_id)
            except Exception as e:
                st.error(f"CSV parse failed: {e}")
    else:
        with st.expander("Replace payments (upload a new CSV)", expanded=False):
            uploaded = st.file_uploader("Upload new CSV", type=["csv"], disabled=read_only)
            if uploaded is not None and not read_only:
                try:
                    tmp = pd.read_csv(uploaded, dtype=str, keep_default_na=False)
                    cols_lower = [c.lower().strip() for c in tmp.columns]
                    if "date" in cols_lower and "amount" in cols_lower:
                        tmp = tmp.rename(columns={tmp.columns[cols_lower.index("date")]: "payment_date",
                                                  tmp.columns[cols_lower.index("amount")]: "amount"})
                    elif "payment_date" in cols_lower and "amount" in cols_lower:
                        tmp = tmp.rename(columns={tmp.columns[cols_lower.index("payment_date")]: "payment_date",
                                                  tmp.columns[cols_lower.index("amount")]: "amount"})
                    else:
                        st.error("CSV must include Date + Amount (or Payment Date + Amount)."); tmp = None
                    if tmp is not None:
                        cleaned = clean_payments_df(tmp); replace_payments(loan_id, cleaned)
                        st.success(f"Imported {len(cleaned)} payments (replaced)."); payments_df = payments_for_loan(loan_id)
                except Exception as e:
                    st.error(f"CSV parse failed: {e}")

    if not read_only:
        st.subheader("Add New Payment")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1: new_date_str = st.text_input("Payment Date (MM/DD/YYYY)", value="", key=f"new_date_str_{loan_id}")
        with c2: new_amount = st.number_input("Amount ($)", min_value=0.00, value=0.00, step=10.0, format="%.2f", key=f"new_amt_{loan_id}")
        with c3:
            if st.button("Add Payment", key=f"addpay_{loan_id}"):
                parsed_date = parse_us_date(new_date_str)
                if parsed_date is None or new_amount <= 0:
                    st.error("Enter a valid date (MM/DD/YYYY) and amount > 0.")
                else:
                    add = payments_df.copy()
                    add = pd.concat([add, pd.DataFrame([{"payment_date": parsed_date, "amount": new_amount}])], ignore_index=True)
                    add = clean_payments_df(add); replace_payments(loan_id, add)
                    st.success("Payment added."); payments_df = payments_for_loan(loan_id)

    label = loan_row.get('loan_name') or loan_row.get('name') or 'Loan'
    st.subheader(f"Ledger — {label} — ACT/365")

    ledger = compute_ledger(
        principal=float(loan_row.get("principal") or 0.0),
        origination_date=pd.to_datetime(loan_row.get("origination_date")).date() if loan_row.get("origination_date") else date.today(),
        annual_rate_decimal=float(loan_row.get("annual_rate") or 0.0) / 100.0,
        payments_df=payments_df,
        grace_days=int(loan_row.get("late_fee_days") or 4),
        late_fee_type=(loan_row.get("late_fee_type") or "fixed"),
        late_fee_amount=float(loan_row.get("late_fee_amount") or 0.0),
    )

    ordered_cols = [
        "Due Date","Payment Date (Posted)","Days Late",
        "Late Fee (Assessed)","Accrued Interest (Cycle)",
        "Allocated → Principal","Principal Balance (End)",
        "Payment Amount (Posted)",
    ]
    col_widths = {
        "Due Date": 88, "Payment Date (Posted)": 108, "Days Late": 70,
        "Late Fee (Assessed)": 118, "Accrued Interest (Cycle)": 132,
        "Allocated → Principal": 128, "Principal Balance (End)": 136,
        "Payment Amount (Posted)": 128
    }
    short_labels = {
        "Due Date":"Due","Payment Date (Posted)":"Pay Date","Days Late":"Days",
        "Late Fee (Assessed)":"Late Fee","Accrued Interest (Cycle)":"Accrued Int",
        "Allocated → Principal":"→ Prin","Principal Balance (End)":"Bal End",
        "Payment Amount (Posted)":"Pay Amt"
    }

    df_to_show = make_display(ledger, ordered_cols)
    render_ledger(df_to_show, col_widths, short_labels, angle_labels=True)

    if not ledger.empty:
        last_row = ledger.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current Principal Balance", f"${float(last_row['Principal Balance (End)']):,.2f}")
        c2.metric("Late Fees (Total)", f"${float(ledger['Late Fee (Assessed)'].sum()):,.2f}")
        c3.metric("Principal Applied (Total)", f"${float(ledger['Allocated → Principal'].sum()):,.2f}")
        last_pay = pd.to_datetime(ledger["Payment Date (Posted)"]).max().date()
        c4.metric("Days Since Last Payment", (date.today() - last_pay).days)

    st.divider()
    a, b = st.columns(2)
    with a:
        base = (loan_row.get('loan_name') or loan_row.get('name') or 'loan').replace(' ', '_')
        st.download_button("⬇️ Download Ledger CSV", data=ledger.to_csv(index=False).encode("utf-8"),
                           file_name=f"ledger_{base}_{date.today().isoformat()}.csv", mime="text/csv")
    with b:
        pdf_bytes = build_pdf_from_ledger(ledger, loan_row)
        base = (loan_row.get('loan_name') or loan_row.get('name') or 'loan').replace(' ', '_')
        st.download_button("📄 Download PDF Statement", data=pdf_bytes,
                           file_name=f"statement_{base}_{date.today().isoformat()}.pdf", mime="application/pdf")

# ---------------- Entry ----------------
def main():
    _inject_global_css()
    if not SUPABASE_OK:
        st.error("⚠️ Supabase connection failed. Check secrets configuration."); st.stop()

    qp = dict(st.query_params)
    if "access_token" in qp or "refresh_token" in qp:
        st.info("🔄 Processing authentication...")
        try:
            if "session" in st.session_state:
                del st.session_state["session"]
            ensure_session_in_state(); st.rerun()
        except Exception as e:
            st.error(f"Auth processing failed: {e}")

    ensure_session_in_state()
    session = st.session_state.get("session")
    token = borrower_token_from_query()
    role_hint = role_from_query()

    if role_hint == "borrower" and token:
        borrower_view_by_token(token); return

    if session and session.user:
        uid = session.user.id
        with st.sidebar:
            st.success(f"✅ Signed in as: {session.user.email or uid}")
            if st.button("🚪 Sign out", key="signout_main"):
                sign_out(); st.rerun()
        if role_hint == "borrower":
            borrower_view_signed_in(uid)
        else:
            lender_view(uid)
        return

    landing()

if __name__ == "__main__":
    main()