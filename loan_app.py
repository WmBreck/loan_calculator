# loan_app.py
# Shylock — Private Loan Servicing (MVP, usability patched)
# Streamlit + Supabase • ACT/365 simple interest • Late fees + Penalty interest
# Centered layout • Mobile-friendly ledger • Lender/Borrower modes

import streamlit as st
st.set_page_config(page_title="Shylock — Private Loan Servicing",
                   page_icon="💸", layout="centered")

from io import BytesIO
from datetime import date, timedelta, datetime as _dt
from decimal import Decimal, ROUND_HALF_UP
import base64
import secrets
import re
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# ---------------------------
# Supabase client
# ---------------------------
try:
    from supabase import create_client, Client
    _sb = st.secrets.get("supabase", {})
    SUPABASE_URL = _sb.get("url")
    SUPABASE_ANON_KEY = _sb.get("anon_key")
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("Missing supabase.url or supabase.anon_key in Streamlit secrets.")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    SUPABASE_OK = True
except Exception as e:
    SUPABASE_OK = False
    supabase = None
    st.error(f"Supabase init failed: {e}")

# ---------------------------
# Global CSS (width, scrolling, sidebar spacing)
# ---------------------------
def _inject_global_css():
    st.markdown(
        """
        <style>
        /* Center main column and cap width for readability */
        .block-container {max-width: 980px; margin: 0 auto;}
        /* Ensure data editors/frames scroll horizontally if wider than container */
        [data-testid="stDataEditor"], [data-testid="stDataFrame"] {overflow: auto !important;}
        /* Sidebar width + reduce vertical spacing a bit */
        @media (min-width: 1000px) {
          [data-testid="stSidebar"] {min-width: 300px; max-width: 320px;}
        }
        section[data-testid="stSidebar"] .stSlider {margin-top:.15rem!important;margin-bottom:.35rem!important;}
        </style>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------
# Helpers: auth, tokens, query params
# ---------------------------
def get_session():
    if not SUPABASE_OK:
        return None
    try:
        return supabase.auth.get_session()
    except Exception:
        return None

def ensure_session_in_state():
    if not SUPABASE_OK:
        return
    if "session" not in st.session_state:
        sess = get_session()
        if sess and getattr(sess, "session", None):
            st.session_state["session"] = sess.session

def _save_tokens_to_state(session_obj):
    """Persist Supabase tokens across reruns."""
    try:
        if session_obj and getattr(session_obj, "access_token", None) and getattr(session_obj, "refresh_token", None):
            st.session_state["sb_tokens"] = {
                "access_token": session_obj.access_token,
                "refresh_token": session_obj.refresh_token,
            }
    except Exception:
        pass

def _restore_session_from_state():
    """If tokens are saved but the client has no session, restore it."""
    try:
        if not SUPABASE_OK:
            return
        current = supabase.auth.get_session()
        if getattr(current, "session", None):
            return
        toks = st.session_state.get("sb_tokens")
        if toks and "access_token" in toks and "refresh_token" in toks:
            supabase.auth.set_session(toks["access_token"], toks["refresh_token"])
            st.session_state["session"] = supabase.auth.get_session().session
    except Exception:
        pass

def sign_out():
    if not SUPABASE_OK:
        return
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
    try:
        st.query_params["role"] = role
    except Exception:
        pass

# ---------------------------
# Header / Wordmark (logo inline)
# ---------------------------
def render_header(
    logo_path: str = "ShylockLogo.png",
    tagline: str = "The humane way to track private personal loans.",
    shylock_color: str = "#00B050",   # green
    online_color: str = "#E32636",    # red
):
    logo_b64 = ""
    p = Path(logo_path)
    if p.exists():
        try:
            logo_b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
        except Exception:
            logo_b64 = ""

    st.markdown(
        f"""
<style>
.shylock-header {{
  display:flex;align-items:center;justify-content:space-between;gap:1rem;
  width:100%;padding:.5rem 0 .75rem;border-bottom:1px solid rgba(0,0,0,.07);flex-wrap:wrap;
}}
.shylock-wordmark {{display:flex;align-items:center;gap:1rem;flex:1 1 auto;min-width:280px;line-height:1;}}
.shylock-text {{
  font-family:"Georgia","Garamond","Times New Roman",serif;font-weight:700;letter-spacing:.5px;
  display:inline-flex;align-items:center;gap:.8rem;white-space:nowrap;
}}
.shylock-text .shylock {{color:{shylock_color};font-size:clamp(32px,4vw,48px);}}
.shylock-text .online  {{color:{online_color}; font-size:clamp(32px,4vw,48px);}}
.shylock-logo {{display:inline-block;width:clamp(36px,4vw,52px);height:clamp(36px,4vw,52px);object-fit:contain;vertical-align:middle;}}
.shylock-tagline {{font-family:"Georgia","Garamond",serif;font-weight:500;font-size:clamp(12px,1.6vw,16px);color:rgba(0,0,0,.72);}}
@media (max-width:900px){{
  .shylock-header{{justify-content:center;}}
  .shylock-tagline{{width:100%;text-align:center;margin-top:.25rem;}}
}}
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

# ---------------------------
# Date helpers (MM/DD/YYYY)
# ---------------------------
def _format_us_date(d):
    try:
        return _dt.strftime(pd.to_datetime(d).to_pydatetime(), "%m/%d/%Y")
    except Exception:
        return ""

def _parse_us_date(s: str):
    if not s or not str(s).strip():
        return None
    s = str(s).strip()
    m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", s)
    if not m:
        return None
    mm, dd, yyyy = map(int, m.groups())
    try:
        return _dt(year=yyyy, month=mm, day=dd).date()
    except Exception:
        return None

# ---------------------------
# DB access
# ---------------------------
def loans_for_lender(user_id: str) -> list[dict]:
    try:
        data = supabase.table("loans").select("*").eq("lender_id", user_id).order("created_at").execute().data
        return data or []
    except Exception:
        return []

def loans_for_borrower_by_token(token: str) -> list[dict]:
    if not token:
        return []
    try:
        data = supabase.table("loans").select("*").eq("borrower_token", token).limit(1).execute().data
        return data or []
    except Exception:
        return []

def loans_for_borrower_signed_in(user_id: str) -> list[dict]:
    """If join table loan_borrowers exists, use it; else return []."""
    try:
        supabase.table("loan_borrowers").select("loan_id").limit(1).execute()
        lb = supabase.table("loan_borrowers").select("loan_id").eq("user_id", user_id).execute().data or []
        loan_ids = [r["loan_id"] for r in lb]
        if not loan_ids:
            return []
        data = supabase.table("loans").select("*").in_("id", loan_ids).order("created_at").execute().data
        return data or []
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
    if df is None or df.empty:
        return
    payload = []
    for _, r in df.iterrows():
        try:
            dt = pd.to_datetime(r["payment_date"]).date().isoformat()
            amt = float(r["amount"])
            if amt <= 0:
                continue
            payload.append({"loan_id": loan_id, "payment_date": dt, "amount": amt})
        except Exception:
            continue
    if payload:
        supabase.table("payments").insert(payload).execute()

# ---------------------------
# Data cleaning
# ---------------------------
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
    amt = (amt
           .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
           .str.replace(",", "", regex=False)
           .str.replace("$", "", regex=False)
           .str.replace("\u00A0", "", regex=False))
    out["amount"] = pd.to_numeric(amt, errors="coerce")
    out = out.dropna(subset=["payment_date", "amount"]).reset_index(drop=True)
    out = out[out["amount"] > 0]
    return out[["payment_date", "amount"]]

# ---------------------------
# Ledger math (ACT/365) + Late Fees + Penalty Interest
# ---------------------------
from datetime import date as _date, timedelta as _timedelta

def _dec(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _prev_due_date(orig: _date, when: _date) -> _date:
    months = (when.year - orig.year) * 12 + (when.month - orig.month)
    if when.day < orig.day:
        months -= 1
    y = orig.year + (orig.month - 1 + months) // 12
    m = ((orig.month - 1 + months) % 12) + 1
    last_day = (_date(y + (m == 12), (m % 12) + 1, 1) - _timedelta(days=1)).day if m != 12 else (_date(y + 1, 1, 1) - _timedelta(days=1)).day
    day = min(orig.day, last_day)
    return _date(y, m, day)

def compute_ledger(
    principal: float,
    origination_date: _date,
    annual_rate_decimal: float,
    payments_df: pd.DataFrame,
    *,
    late_fee_type: str = "fixed",
    late_fee_amount: float = 0.0,
    late_fee_days: int = 0,
    penalty_apr_decimal: float | None = None,
) -> pd.DataFrame:
    df = clean_payments_df(payments_df)
    df = df[df["payment_date"] >= origination_date].sort_values("payment_date").reset_index(drop=True)

    bal_p = _dec(principal)
    out_late = _dec(0)
    out_pen_i = _dec(0)
    loan_i_carry = _dec(0)
    last_event_date = origination_date

    apr_p = Decimal(str(annual_rate_decimal))
    apr_pen = Decimal(str(penalty_apr_decimal if penalty_apr_decimal not in (None, 0) else annual_rate_decimal))

    rows = []

    for _, r in df.iterrows():
        pay_dt = r["payment_date"]
        pay_amt = _dec(r["amount"])
        due_dt = _prev_due_date(origination_date, pay_dt)

        # 1) Loan interest accrual since last event
        days_loan = max((pay_dt - last_event_date).days, 0)
        accrued_loan_i = (bal_p * apr_p * Decimal(days_loan) / Decimal(365)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        loan_i_due = (accrued_loan_i + loan_i_carry).quantize(Decimal("0.01"))

        # 2) Assess late fee if past grace
        new_late_fee = _dec(0)
        if late_fee_days is not None and late_fee_days >= 0:
            if pay_dt > (due_dt + timedelta(days=int(late_fee_days))):
                if late_fee_type == "percent":
                    ref = (bal_p * apr_p / Decimal(12)).quantize(Decimal("0.01"))  # approx 1 month interest
                    new_late_fee = (ref * Decimal(late_fee_amount) / Decimal(100)).quantize(Decimal("0.01"))
                else:
                    new_late_fee = _dec(late_fee_amount)
                if new_late_fee > 0:
                    out_late = (out_late + new_late_fee).quantize(Decimal("0.01"))

        # 3) Penalty interest accrual on outstanding late fees
        days_pen = max((pay_dt - last_event_date).days, 0)
        accrued_pen_i = (out_late * apr_pen * Decimal(days_pen) / Decimal(365)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out_pen_i = (out_pen_i + accrued_pen_i).quantize(Decimal("0.01"))

        # 4) Allocation order
        remaining = pay_amt
        alloc_pen_i = min(remaining, out_pen_i); remaining -= alloc_pen_i; out_pen_i -= alloc_pen_i
        alloc_late  = min(remaining, out_late);  remaining -= alloc_late;  out_late  -= alloc_late
        alloc_loan_i = min(remaining, loan_i_due); remaining -= alloc_loan_i; loan_i_due -= alloc_loan_i
        alloc_prin  = remaining; remaining = _dec(0); bal_p = (bal_p - alloc_prin).quantize(Decimal("0.01"))
        loan_i_carry = loan_i_due

        rows.append({
            "Payment Date": pay_dt,
            "Due Date": due_dt,
            "Payment Amount": (alloc_pen_i + alloc_late + alloc_loan_i + alloc_prin),
            "Accrued Loan Interest": (accrued_loan_i + loan_i_carry),
            "Penalty Interest Accrued": accrued_pen_i,
            "Late Fee (Assessed)": new_late_fee,
            "Allocated → Penalty Interest": alloc_pen_i,
            "Allocated → Late Fees": alloc_late,
            "Allocated → Loan Interest": alloc_loan_i,
            "Allocated → Principal": alloc_prin,
            "Principal Balance (End)": bal_p,
            "Late Fees Outstanding (End)": out_late,
            "Penalty Interest Outstanding (End)": out_pen_i
        })

        last_event_date = pay_dt

    return pd.DataFrame(rows)

# ---------------------------
# PDF builder
# ---------------------------
def build_pdf_from_ledger(ledger: pd.DataFrame, loan_meta: dict) -> bytes:
    buf = BytesIO()
    pp = PdfPages(buf)

    fig = plt.figure(figsize=(8.5, 11))
    fig.clf()
    plt.axis('off')

    loan_label = loan_meta.get('loan_name') or loan_meta.get('name') or 'Loan'
    title = "Loan Statement"
    subtitle = f"{loan_label} — Generated {date.today():%b %d, %Y}"
    lines = [
        title, subtitle, "",
        f"Lender: {loan_meta.get('lender_name','')}",
        f"Borrower: {loan_meta.get('borrower_name','')}",
        f"Origination: {_format_us_date(loan_meta.get('origination_date')) or '—'}",
        f"APR: {float(loan_meta.get('annual_rate', 0.0)):.3f}% (ACT/365 simple interest)",
        f"Late Fee: {loan_meta.get('late_fee_type','fixed')} {loan_meta.get('late_fee_amount',0)}; "
        f"Grace: {loan_meta.get('late_fee_days',0)} day(s); "
        f"Penalty APR: {float(loan_meta.get('penalty_interest_rate') or 0.0):.3f}%",
        "",
    ]

    if not ledger.empty:
        begin_prin = float(ledger.iloc[0]["Principal Balance (End)"] + ledger.iloc[0]["Allocated → Principal"])
        end_prin = float(ledger.iloc[-1]["Principal Balance (End)"])
        tot_pay = float(ledger["Payment Amount"].sum())
        tot_pen_int = float(ledger["Allocated → Penalty Interest"].sum())
        tot_late = float(ledger["Allocated → Late Fees"].sum())
        tot_int = float(ledger["Allocated → Loan Interest"].sum())
        out_late = float(ledger.iloc[-1]["Late Fees Outstanding (End)"])
        out_pen = float(ledger.iloc[-1]["Penalty Interest Outstanding (End)"])
    else:
        begin_prin = float(loan_meta.get("principal", 0.0))
        end_prin = begin_prin
        tot_pay = tot_pen_int = tot_late = tot_int = out_late = out_pen = 0.0

    summary_lines = [
        f"Beginning Principal Balance: ${begin_prin:,.2f}",
        f"Payments Received (Total): ${tot_pay:,.2f}",
        f"Allocated to Penalty Interest: ${tot_pen_int:,.2f}",
        f"Allocated to Late Fees: ${tot_late:,.2f}",
        f"Allocated to Loan Interest: ${tot_int:,.2f}",
        f"Allocated to Principal: ${tot_pay - tot_pen_int - tot_late - tot_int:,.2f}",
        f"Ending Principal Balance: ${end_prin:,.2f}",
        f"Outstanding Late Fees: ${out_late:,.2f}",
        f"Outstanding Penalty Interest: ${out_pen:,.2f}",
        "",
        "Allocation order: Penalty Interest → Late Fees → Loan Interest → Principal",
        "Disclaimer: This statement is informational only. Lender is responsible for any required legal disclosures.",
    ]

    y = 0.95
    for s in lines:
        plt.text(0.05, y, s, ha='left', va='top', fontsize=11,
                 family='sans-serif', weight='bold' if s == title else 'normal')
        y -= 0.035
    y -= 0.01
    for s in summary_lines:
        plt.text(0.05, y, s, ha='left', va='top', fontsize=10, family='monospace')
        y -= 0.028

    pp.savefig(fig, bbox_inches='tight')
    plt.close(fig)

    if not ledger.empty:
        dfp = ledger.copy()
        dfp["Payment Date"] = pd.to_datetime(dfp["Payment Date"]).dt.strftime("%Y-%m-%d")
        dfp["Due Date"] = pd.to_datetime(dfp["Due Date"]).dt.strftime("%Y-%m-%d")
        cols = [
            "Payment Date", "Due Date", "Payment Amount",
            "Penalty Interest Accrued", "Late Fee (Assessed)",
            "Allocated → Penalty Interest", "Allocated → Late Fees",
            "Allocated → Loan Interest", "Allocated → Principal",
            "Principal Balance (End)", "Late Fees Outstanding (End)",
            "Penalty Interest Outstanding (End)"
        ]
        rows_per_page = 24
        for start in range(0, len(dfp), rows_per_page):
            chunk = dfp.iloc[start:start + rows_per_page][cols]
            fig = plt.figure(figsize=(8.5, 11))
            ax = fig.add_subplot(111)
            ax.axis('off')
            ax.set_title("Payment & Accrual Activity", fontsize=12, pad=16)
            tbl = ax.table(cellText=chunk.values, colLabels=chunk.columns, loc='center')
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(7.5)
            tbl.scale(1, 1.2)
            pp.savefig(fig, bbox_inches='tight')
            plt.close(fig)

    pp.close()
    buf.seek(0)
    return buf.getvalue()

# ---------------------------
# UI: Landing
# ---------------------------
def landing():
    render_header()
    st.title("Welcome")
    st.write("Track irregular payments, allocate interest/fees/principal correctly, and export clean statements.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("I’m a Lender (Manage Loans)", use_container_width=True):
            set_role_in_url("lender")
            st.rerun()
    with c2:
        if st.button("I’m a Borrower (View Only)", use_container_width=True):
            set_role_in_url("borrower")
            st.rerun()

    st.divider()
    st.subheader("Sign in / Sign up")

    with st.expander("Email & Password", expanded=True):
        email = st.text_input("Email")
        pw = st.text_input("Password", type="password")
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            if st.button("Sign Up", use_container_width=True, key="signup_btn"):
                if not email or not pw:
                    st.error("Please enter both email and password.")
                else:
                    try:
                        supabase.auth.sign_up({
                            "email": email,
                            "password": pw,
                            "options": {"email_redirect_to": "http://localhost:8501"}
                        })
                        st.success(f"Signup initiated. Check your email ({email}) to confirm.")
                    except Exception as e:
                        st.error(f"Signup error: {e}")
        with cc2:
            if st.button("Sign In", use_container_width=True, key="signin_btn"):
                if not email or not pw:
                    st.error("Please enter both email and password.")
                else:
                    try:
                        res = supabase.auth.sign_in_with_password({"email": email, "password": pw})
                        st.session_state["session"] = res.session
                        _save_tokens_to_state(res.session)
                        st.success(f"✅ Signed in as {email}")
                        try:
                            uid = res.user.id
                            prof = supabase.table("profiles").select("id").eq("id", uid).single().execute()
                            if not prof.data:
                                supabase.table("profiles").insert({"id": uid, "email": email, "company_name": "Your Company"}).execute()
                        except Exception:
                            pass
                        st.rerun()
                    except Exception as e:
                        st.error(f"Sign in error: {e}")
        with cc3:
            if st.button("Send Magic Link", use_container_width=True, key="magic_btn"):
                if not email:
                    st.error("Enter your email first.")
                else:
                    try:
                        supabase.auth.sign_in_with_otp({"email": email, "options": {"email_redirect_to": "http://localhost:8501"}})
                        st.success(f"Magic link sent to {email}")
                    except Exception as e:
                        st.error(f"Magic link error: {e}")

    st.caption("OAuth (Google/Apple) can be enabled later via Supabase Auth providers.")

# ---------------------------
# UI: Borrower Views (read-only)
# ---------------------------
def borrower_view_by_token(token: str):
    render_header()
    rows = loans_for_borrower_by_token(token)
    if not rows:
        st.error("Invalid or expired borrower link.")
        return
    loan = rows[0]
    label = loan.get('loan_name') or loan.get('name') or 'Loan'
    st.title(f"📋 Loan Statement — {label}")
    _common_loan_view(loan, read_only=True)

def borrower_view_signed_in(user_id: str):
    render_header()
    rows = loans_for_borrower_signed_in(user_id)
    st.title("📋 Your Loans (Borrower)")
    if not rows:
        st.info("No loans are shared with this account.")
        return
    names = [f"{(r.get('loan_name') or r.get('name') or 'Loan')} — {r.get('borrower_name','(Borrower?)')}" for r in rows]
    idx = st.selectbox("Select loan", range(len(rows)), format_func=lambda i: names[i])
    loan = rows[idx]
    _common_loan_view(loan, read_only=True)

# ---------------------------
# UI: Lender View (create/edit)
# ---------------------------
def lender_view(user_id: str):
    render_header()
    st.title("💸 Manage Loans & Statements")
    st.caption("Irregular payments • ACT/365 simple interest • Late fees + penalty interest")

    try:
        user_profile = supabase.table("profiles").select("company_name").eq("id", user_id).single().execute()
        company_name = user_profile.data.get("company_name", "Your Company") if user_profile.data else "Your Company"
    except Exception:
        company_name = "Your Company"
    st.info(f"🏢 Managing loans for **{company_name}**")

    loans = loans_for_lender(user_id)

    t1, t2, t3 = st.columns([1.5, 1, 1])
    with t1:
        if st.button("➕ New Loan"):
            try:
                new = {
                    "lender_id": user_id,
                    "lender_name": company_name,
                    "loan_name": f"Loan {len(loans)+1}",
                    "principal": 100000.0,
                    "origination_date": date.today().isoformat(),
                    "annual_rate": 5.0,
                    "term_years": 30,
                    "borrower_name": "To be set",
                    "borrower_email": "to_be_set@example.com",
                    "borrower_token": secrets.token_urlsafe(24),
                }
                upsert_loan(new)
                st.rerun()
            except Exception as e:
                st.error(f"Create loan failed: {e}")
    with t2:
        if st.button("🔄 Refresh"):
            st.rerun()
    with t3:
        if st.button("🚪 Sign out"):
            sign_out()
            st.rerun()

    if not loans:
        st.info("No loans yet. Click **New Loan** to create one.")
        return

    st.caption(f"Active loans found: {len(loans)}")
    show_ids = st.checkbox("Show loan IDs", value=False, help="Enable to display the short loan id in the selector")
    sel = st.selectbox(
        "Select Loan",
        options=range(len(loans)),
        format_func=lambda i: (
            f"{(loans[i].get('loan_name') or loans[i].get('name') or 'Loan')} — {loans[i].get('borrower_name','(Borrower?)')}"
            + (f" — {loans[i]['id'][:8]}" if show_ids else "")
        )
    )
    loan = loans[sel]

    # Sidebar (lender-only actions)
    with st.sidebar:
        st.header("💰 Loan Terms")
        name_val = loan.get("loan_name") or loan.get("name","")
        name = st.text_input("Loan Name", value=name_val)
        borrower_name = st.text_input("Borrower Name", value=loan.get("borrower_name",""))
        principal = st.number_input("Original Principal ($)", min_value=0.0, value=float(loan.get("principal") or 0.0), step=1000.0, format="%.2f")

        # MM/DD/YYYY origination date input
        origination_date_str = st.text_input("Origination Date (MM/DD/YYYY)",
                                             value=_format_us_date(loan.get("origination_date")),
                                             help="Enter as MM/DD/YYYY (leading zeros optional)")
        parsed_orig = _parse_us_date(origination_date_str)
        if parsed_orig is None:
            st.warning("Enter a valid date like 08/31/2023")
        origination_date_val = parsed_orig or (
            pd.to_datetime(loan.get("origination_date")).date() if loan.get("origination_date") else date.today()
        )

        annual_rate_pct = st.number_input("Interest Rate (APR %)", min_value=0.0, value=float(loan.get("annual_rate") or 0.0), step=0.1, format="%.3f")
        term_years = st.number_input("Loan Term (years)", min_value=1, value=int(loan.get("term_years") or 30), step=1)

        st.divider()
        st.subheader("Late Fee Rules")
        late_fee_type = st.selectbox("Late Fee Type", ["fixed", "percent"], index=0 if loan.get("late_fee_type") in (None, "fixed") else 1)
        late_fee_amount = st.number_input("Late Fee Amount ($ or %)", min_value=0.0, value=float(loan.get("late_fee_amount") or 0.0), step=1.0, format="%.2f")
        late_fee_days = st.number_input("Grace Period (days)", min_value=0, value=int(loan.get("late_fee_days") or 0), step=1)
        penalty_apr = st.number_input("Penalty Interest APR (%) (optional)", min_value=0.0, value=float(loan.get("penalty_interest_rate") or 0.0), step=0.1, format="%.3f")

        with st.expander("Borrower link (read-only)", expanded=False):
            st.code(f"?role=borrower&token={loan.get('borrower_token')}", language="text")
            if st.button("Generate New Borrower Token"):
                loan["borrower_token"] = secrets.token_urlsafe(32)
                upsert_loan(loan)
                st.success("New borrower token generated.")

        st.markdown("### Actions")
        colA, colB = st.columns(2)
        with colA:
            save_clicked = st.button("💾 Save Loan", use_container_width=True)
        with colB:
            del_clicked = st.button("🗑️ Delete Loan", use_container_width=True)

        if save_clicked:
            loan.update({
                "loan_name": name,
                "borrower_name": borrower_name,
                "principal": principal,
                "origination_date": origination_date_val.isoformat(),
                "annual_rate": annual_rate_pct,
                "term_years": int(term_years),
                "late_fee_type": late_fee_type,
                "late_fee_amount": late_fee_amount,
                "late_fee_days": int(late_fee_days),
                "penalty_interest_rate": penalty_apr,
            })
            try:
                upsert_loan(loan)
                st.success("Saved.")
                st.rerun()
            except Exception as e:
                msg = str(e)
                if "PGRST204" in msg or "schema cache" in msg:
                    for k in ["late_fee_type", "late_fee_amount", "late_fee_days", "penalty_interest_rate"]:
                        loan.pop(k, None)
                    try:
                        upsert_loan(loan)
                        st.warning("Saved without late-fee fields. Run migrations.sql in Supabase, then click 🔄 Refresh.")
                        st.rerun()
                    except Exception as e2:
                        st.error(f"Save failed (legacy retry): {e2}")
                else:
                    st.error(f"Save failed: {e}")

        if del_clicked:
            try:
                delete_loan(loan["id"])
                st.warning("Loan deleted.")
                st.rerun()
            except Exception as e:
                st.error(f"Delete failed: {e}")

    _common_loan_view(loan, read_only=False)

# ---------------------------
# Shared loan view (payments + ledger + exports)
# ---------------------------
def _common_loan_view(loan_row: dict, read_only: bool):
    loan_id = loan_row["id"]
    payments_df = payments_for_loan(loan_id)

    st.subheader("Payments")
    st.caption("Upload CSV with columns: Date, Amount (or Payment Date, Amount). Positive amounts are payments.")

    # CSV upload (hide after initial; expander to replace)
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
                    st.error("CSV must include columns: Date, Amount (or Payment Date, Amount).")
                    tmp = None
                if tmp is not None:
                    cleaned = clean_payments_df(tmp)
                    replace_payments(loan_id, cleaned)
                    st.success(f"Imported {len(cleaned)} payments.")
                    payments_df = payments_for_loan(loan_id)
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
                        st.error("CSV must include columns: Date, Amount (or Payment Date, Amount).")
                        tmp = None
                    if tmp is not None:
                        cleaned = clean_payments_df(tmp)
                        replace_payments(loan_id, cleaned)
                        st.success(f"Imported {len(cleaned)} payments (replaced).")
                        payments_df = payments_for_loan(loan_id)
                except Exception as e:
                    st.error(f"CSV parse failed: {e}")

    # Helper: warn if origination date > earliest payment
    if not payments_df.empty and loan_row.get("origination_date"):
        earliest = pd.to_datetime(payments_df["payment_date"]).min().date()
        orig_dt = pd.to_datetime(loan_row.get("origination_date")).date()
        if orig_dt > earliest:
            st.warning(f"Origination date ({_format_us_date(orig_dt)}) is after earliest payment ({_format_us_date(earliest)}). "
                       f"Set origination date on or before {_format_us_date(earliest)} to include all payments in the ledger.")

    # Add New Payment (date string + amount default 0.00)
    if not read_only:
        st.subheader("Add New Payment")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            new_date_str = st.text_input("Payment Date (MM/DD/YYYY)", value="", key=f"new_date_str_{loan_id}")
        with c2:
            new_amount = st.number_input("Amount ($)", min_value=0.00, value=0.00, step=10.0, format="%.2f", key=f"new_amt_{loan_id}")
        with c3:
            if st.button("Add Payment", key=f"addpay_{loan_id}"):
                parsed_new_date = _parse_us_date(new_date_str)
                if parsed_new_date is None or new_amount <= 0:
                    st.error("Enter a valid date (MM/DD/YYYY) and amount > 0.")
                else:
                    add = payments_df.copy()
                    add = pd.concat([add, pd.DataFrame([{"payment_date": parsed_new_date, "amount": new_amount}])], ignore_index=True)
                    add = clean_payments_df(add)
                    replace_payments(loan_id, add)
                    st.success("Payment added.")
                    payments_df = payments_for_loan(loan_id)

    label = loan_row.get('loan_name') or loan_row.get('name') or 'Loan'
    st.subheader(f"Ledger — {label} (Late Fees + Penalty Interest) — ACT/365")

    # Mobile-friendly option: core columns by default
    mobile_view = st.checkbox("Mobile view (core columns only)", value=True,
                              help="Show fewer columns for small screens")
    ledger = compute_ledger(
        principal=float(loan_row.get("principal") or 0.0),
        origination_date=pd.to_datetime(loan_row.get("origination_date")).date() if loan_row.get("origination_date") else date.today(),
        annual_rate_decimal=float(loan_row.get("annual_rate") or 0.0) / 100.0,
        payments_df=payments_df,
        late_fee_type=loan_row.get("late_fee_type", "fixed"),
        late_fee_amount=float(loan_row.get("late_fee_amount") or 0.0),
        late_fee_days=int(loan_row.get("late_fee_days") or 0),
        penalty_apr_decimal=(float(loan_row.get("penalty_interest_rate"))/100.0 if loan_row.get("penalty_interest_rate") else None),
    )

    df_to_show = ledger[[
        "Payment Date", "Due Date", "Payment Amount",
        "Allocated → Loan Interest", "Allocated → Principal",
        "Principal Balance (End)"
    ]] if mobile_view else ledger

    compact_cols = st.checkbox("Compact column widths", value=True,
                               help="Toggle to fit more columns without horizontal scrolling.")

    column_widths = {
        "Payment Date": 110, "Due Date": 110,
        "Payment Amount": 110, "Accrued Loan Interest": 130,
        "Penalty Interest Accrued": 150, "Late Fee (Assessed)": 130,
        "Allocated → Penalty Interest": 150, "Allocated → Late Fees": 140,
        "Allocated → Loan Interest": 150, "Allocated → Principal": 130,
        "Principal Balance (End)": 160, "Late Fees Outstanding (End)": 180,
        "Penalty Interest Outstanding (End)": 200
    }
    if compact_cols:
        for k in column_widths:
            column_widths[k] = max(100, int(column_widths[k] * 0.85))

    st.data_editor(
        df_to_show,
        use_container_width=True,
        hide_index=True,
        disabled=True,
        height=480,
        column_config={
            "Payment Date": st.column_config.DateColumn(format="MM/DD/YYYY", width=column_widths["Payment Date"]),
            "Due Date": st.column_config.DateColumn(format="MM/DD/YYYY", width=column_widths["Due Date"]),
            "Payment Amount": st.column_config.NumberColumn(format="$%.2f", width=column_widths["Payment Amount"]),
            "Accrued Loan Interest": st.column_config.NumberColumn(format="$%.2f", width=column_widths.get("Accrued Loan Interest", 130)),
            "Penalty Interest Accrued": st.column_config.NumberColumn(format="$%.2f", width=column_widths.get("Penalty Interest Accrued", 150)),
            "Late Fee (Assessed)": st.column_config.NumberColumn(format="$%.2f", width=column_widths.get("Late Fee (Assessed)", 130)),
            "Allocated → Penalty Interest": st.column_config.NumberColumn(format="$%.2f", width=column_widths.get("Allocated → Penalty Interest", 150)),
            "Allocated → Late Fees": st.column_config.NumberColumn(format="$%.2f", width=column_widths.get("Allocated → Late Fees", 140)),
            "Allocated → Loan Interest": st.column_config.NumberColumn(format="$%.2f", width=column_widths["Allocated → Loan Interest"]),
            "Allocated → Principal": st.column_config.NumberColumn(format="$%.2f", width=column_widths["Allocated → Principal"]),
            "Principal Balance (End)": st.column_config.NumberColumn(format="$%.2f", width=column_widths["Principal Balance (End)"]),
            "Late Fees Outstanding (End)": st.column_config.NumberColumn(format="$%.2f", width=column_widths.get("Late Fees Outstanding (End)", 180)),
            "Penalty Interest Outstanding (End)": st.column_config.NumberColumn(format="$%.2f", width=column_widths.get("Penalty Interest Outstanding (End)", 200)),
        },
        key="ledger_grid_readonly"
    )

    if not ledger.empty:
        last_row = ledger.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current Principal Balance", f"${float(last_row['Principal Balance (End)']):,.2f}")
        c2.metric("Outstanding Late Fees", f"${float(last_row['Late Fees Outstanding (End)']):,.2f}")
        c3.metric("Outstanding Penalty Interest", f"${float(last_row['Penalty Interest Outstanding (End)']):,.2f}")
        last_pay = pd.to_datetime(ledger["Payment Date"]).max().date()
        c4.metric("Days Since Last Payment", (date.today() - last_pay).days)

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("⬇️ Download CSV"):
            csv_bytes = ledger.to_csv(index=False).encode("utf-8")
            base = (loan_row.get('loan_name') or loan_row.get('name') or 'loan').replace(' ', '_')
            st.download_button("Download Ledger CSV", data=csv_bytes,
                               file_name=f"ledger_{base}_{date.today().isoformat()}.csv",
                               mime="text/csv")
    with c2:
        if st.button("📄 Generate PDF"):
            pdf_bytes = build_pdf_from_ledger(ledger, loan_row)
            base = (loan_row.get('loan_name') or loan_row.get('name') or 'loan').replace(' ', '_')
            st.download_button("Download PDF Statement", data=pdf_bytes,
                               file_name=f"statement_{base}_{date.today().isoformat()}.pdf",
                               mime="application/pdf")

# ---------------------------
# App entry
# ---------------------------
def main():
    _inject_global_css()
    _restore_session_from_state()

    if not SUPABASE_OK:
        st.error("⚠️ Supabase connection failed. Check secrets configuration.")
        st.stop()

    qp = dict(st.query_params)
    if "access_token" in qp or "refresh_token" in qp:
        st.info("🔄 Processing authentication...")
        try:
            if "session" in st.session_state:
                del st.session_state["session"]
            ensure_session_in_state()
            st.rerun()
        except Exception as e:
            st.error(f"Auth processing failed: {e}")

    ensure_session_in_state()
    session = st.session_state.get("session")
    token = borrower_token_from_query()
    role_hint = role_from_query()

    # Borrower via token link (read-only)
    if role_hint == "borrower" and token:
        borrower_view_by_token(token)
        return

    # Signed in
    if session and session.user:
        uid = session.user.id
        with st.sidebar:
            st.success(f"✅ Signed in as: {session.user.email or uid}")
            if st.button("🚪 Sign out", key="signout_main"):
                sign_out()
                st.rerun()
        if role_hint == "borrower":
            borrower_view_signed_in(uid)
        else:
            lender_view(uid)
        return

    # Not signed in
    landing()

if __name__ == "__main__":
    main()