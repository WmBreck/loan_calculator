# loan_app.py
# Shylock — Private Loan Servicing (MVP)
# Streamlit + Supabase • Late Fees + Penalty Interest • ACT/365 simple interest
# Uses loans.loan_name (with fallback to legacy loans.name for display).

import streamlit as st
st.set_page_config(page_title="Shylock — Private Loan Servicing", page_icon="💸", layout="wide")

from io import BytesIO
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import secrets

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
# Helpers: auth + query params
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
    # Modern Streamlit API only (no deprecated experimental calls)
    return st.query_params.get(name, default)

def role_from_query() -> str | None:
    return st.session_state.get("role") or qp_get("role")

def borrower_token_from_query() -> str | None:
    return qp_get("token")
# ---------------------------
# Logo display
# ---------------------------
def display_logo():
    """Display the Shylock logo at the top of each page"""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("ShylockLogo.png", width=200, use_column_width=False)
    st.divider()


def set_role_in_url(role: str):
    st.session_state["role"] = role
    try:
        st.query_params["role"] = role
    except Exception:
        pass


# ---------------------------
# DB access (current schema friendly)
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
    """Optional join table loan_borrowers(user_id, loan_id). If absent, return []."""
    try:
        # Probe existence
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
# Ledger math (ACT/365 simple) with Late Fees + Penalty Interest
# ---------------------------
def _dec(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _prev_due_date(orig: date, when: date) -> date:
    """Previous monthly due date anchored to origination day; clamps month-end properly."""
    months = (when.year - orig.year) * 12 + (when.month - orig.month)
    if when.day < orig.day:
        months -= 1
    y = orig.year + (orig.month - 1 + months) // 12
    m = ((orig.month - 1 + months) % 12) + 1
    # Compute last day of month m in year y
    if m == 12:
        last_day = (date(y + 1, 1, 1) - timedelta(days=1)).day
    else:
        last_day = (date(y, m + 1, 1) - timedelta(days=1)).day
    day = min(orig.day, last_day)
    return date(y, m, day)

def compute_ledger(
    principal: float,
    origination_date: date,
    annual_rate_decimal: float,
    payments_df: pd.DataFrame,
    *,
    late_fee_type: str = "fixed",              # "fixed" | "percent"
    late_fee_amount: float = 0.0,              # fixed $ or percent number
    late_fee_days: int = 0,                    # grace period days
    penalty_apr_decimal: float | None = None,  # if None, use loan APR
) -> pd.DataFrame:
    """
    Produces a ledger with columns:
      Due Date, Payment Date, Payment Amount, Accrued Loan Interest, Penalty Interest Accrued,
      Late Fee (Assessed), Allocated → Penalty Interest, Allocated → Late Fees,
      Allocated → Loan Interest, Allocated → Principal, Principal Balance (End),
      Late Fees Outstanding (End), Penalty Interest Outstanding (End)
    Rules:
      - ACT/365 simple interest on principal only
      - Unpaid loan interest is carried (does NOT itself accrue interest)
      - Late fees accrue penalty interest daily (no compounding of that interest bucket)
      - Allocation order: Penalty Int → Late Fees → Loan Interest → Principal
      - Late fee assessment: if payment_date > (due_date + grace)
        * percent late fee is percent of a reference "scheduled" payment (here: interest-only proxy)
    """
    df = clean_payments_df(payments_df)
    df = df[df["payment_date"] >= origination_date].sort_values("payment_date").reset_index(drop=True)

    bal_p = _dec(principal)                # principal balance
    out_late = _dec(0)                     # outstanding late-fee principal
    out_pen_i = _dec(0)                    # outstanding penalty interest
    loan_i_carry = _dec(0)                 # unpaid loan interest (does not accrue interest)
    last_event_date = origination_date

    apr_p = Decimal(str(annual_rate_decimal))
    apr_pen = Decimal(str(penalty_apr_decimal if penalty_apr_decimal not in (None, 0) else annual_rate_decimal))

    rows = []

    for _, r in df.iterrows():
        pay_dt = r["payment_date"]
        pay_amt = _dec(r["amount"])

        # Determine most recent due date relative to payment
        due_dt = _prev_due_date(origination_date, pay_dt)

        # 1) Accrue loan interest on principal since last event
        days_loan = max((pay_dt - last_event_date).days, 0)
        accrued_loan_i = (bal_p * apr_p * Decimal(days_loan) / Decimal(365)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        loan_i_due = (accrued_loan_i + loan_i_carry).quantize(Decimal("0.01"))

        # 2) Maybe assess new late fee (MVP: at most one per payment event)
        new_late_fee = _dec(0)
        if late_fee_days is not None and late_fee_days >= 0:
            if pay_dt > (due_dt + timedelta(days=int(late_fee_days))):
                if late_fee_type == "percent":
                    # reference = interest-only proxy (monthly)
                    ref = (bal_p * apr_p / Decimal(12)).quantize(Decimal("0.01"))
                    new_late_fee = (ref * Decimal(late_fee_amount) / Decimal(100)).quantize(Decimal("0.01"))
                else:
                    new_late_fee = _dec(late_fee_amount)
                if new_late_fee > 0:
                    out_late = (out_late + new_late_fee).quantize(Decimal("0.01"))

        # 3) Accrue penalty interest on outstanding late-fee principal since last event
        days_pen = max((pay_dt - last_event_date).days, 0)
        accrued_pen_i = (out_late * apr_pen * Decimal(days_pen) / Decimal(365)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out_pen_i = (out_pen_i + accrued_pen_i).quantize(Decimal("0.01"))

        # 4) Allocate payment
        remaining = pay_amt

        alloc_pen_i = min(remaining, out_pen_i); remaining -= alloc_pen_i; out_pen_i -= alloc_pen_i
        alloc_late  = min(remaining, out_late);  remaining -= alloc_late;  out_late  -= alloc_late
        alloc_loan_i = min(remaining, loan_i_due); remaining -= alloc_loan_i; loan_i_due -= alloc_loan_i
        alloc_prin  = remaining; remaining = _dec(0); bal_p = (bal_p - alloc_prin).quantize(Decimal("0.01"))

        # Remaining unpaid loan interest becomes new carry (no compounding)
        loan_i_carry = loan_i_due

        rows.append({
            "Payment Date": pay_dt,
            "Due Date": due_dt,
            "Payment Amount": (alloc_pen_i + alloc_late + alloc_loan_i + alloc_prin),
            "Accrued Loan Interest": (accrued_loan_i + loan_i_carry),  # what accrued incl. any unpaid carry
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
# PDF Builder (Matplotlib)
# ---------------------------
def build_pdf_from_ledger(ledger: pd.DataFrame, loan_meta: dict) -> bytes:
    buf = BytesIO()
    pp = PdfPages(buf)

    # --- Summary page ---
    fig = plt.figure(figsize=(8.5, 11))
    fig.clf()
    plt.axis('off')

    loan_label = loan_meta.get('loan_name') or loan_meta.get('name') or 'Loan'
    title = "Loan Statement"
    subtitle = f"{loan_label} — Generated {date.today():%b %d, %Y}"
    lines = [
        title,
        subtitle,
        "",
        f"Lender: {loan_meta.get('lender_name','')}",
        f"Borrower: {loan_meta.get('borrower_name','')}",
        f"Origination: {pd.to_datetime(loan_meta.get('origination_date')).date():%b %d, %Y}" if loan_meta.get('origination_date') else "Origination: —",
        f"APR: {float(loan_meta.get('annual_rate', 0.0)):.3f}% (ACT/365 simple interest)",
        f"Late Fee: {loan_meta.get('late_fee_type','fixed')} {loan_meta.get('late_fee_amount',0)}; "
        f"Grace: {loan_meta.get('late_fee_days',0)} day(s); "
        f"Penalty APR: {float(loan_meta.get('penalty_interest_rate') or 0.0):.3f}%",
        "",
    ]

    # Compute summary totals
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
        plt.text(0.05, y, s, ha='left', va='top', fontsize=11, family='sans-serif', weight='bold' if s == title else 'normal')
        y -= 0.035
    y -= 0.01
    for s in summary_lines:
        plt.text(0.05, y, s, ha='left', va='top', fontsize=10, family='monospace')
        y -= 0.028

    pp.savefig(fig, bbox_inches='tight')
    plt.close(fig)

    # --- Ledger pages ---
    if not ledger.empty:
        dfp = ledger.copy()
        dfp["Payment Date"] = pd.to_datetime(dfp["Payment Date"]).dt.strftime("%Y-%m-%d")
        dfp["Due Date"] = pd.to_datetime(dfp["Due Date"]).dt.strftime("%Y-%m-%d")

        cols = [
            "Payment Date", "Due Date", "Payment Amount",
            "Penalty Interest Accrued", "Late Fee (Assessed)",
            "Allocated → Penalty Interest", "Allocated → Late Fees",
            "Allocated → Loan Interest", "Allocated → Principal",
            "Principal Balance (End)", "Late Fees Outstanding (End)", "Penalty Interest Outstanding (End)"
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
     display_logo()  # Add logo here
     st.title("Shylock — Private Loan Servicing")
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
                        st.success(f"✅ Signed in as {email}")
                        # Ensure profile exists (profiles.id == auth.users.id)
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
# UI: Borrower Views
# ---------------------------
def borrower_view_by_token(token: str):
     display_logo()  # Add logo here
     rows = loans_for_borrower_by_token(token)
    if not rows:
        st.error("Invalid or expired borrower link.")
        return
    loan = rows[0]
    label = loan.get('loan_name') or loan.get('name') or 'Loan'
    st.title(f"📋 Loan Statement — {label}")
    _common_loan_view(loan, read_only=True)

def borrower_view_signed_in(user_id: str):
    display_logo()  # Add logo here
    rows = loans_for_borrower_signed_in(user_id)
    st.title("📋 Your Loans (Borrower)")
    if not rows:
        st.info("No loans are shared with this account.")
        return
    names = [f"{(r.get('loan_name') or r.get('name') or 'Loan')} — {r['id'][:8]}" for r in rows]
    idx = st.selectbox("Select loan", range(len(rows)), format_func=lambda i: names[i])
    loan = rows[idx]
    _common_loan_view(loan, read_only=True)


# ---------------------------
# UI: Lender View
# ---------------------------
def lender_view(user_id: str):
     display_logo()  # Add logo here
     st.title("💸 Manage Loans & Statements")
    st.caption("Irregular payments • ACT/365 simple interest • Late fees + penalty interest")

    # Company banner
    try:
        user_profile = supabase.table("profiles").select("company_name").eq("id", user_id).single().execute()
        company_name = user_profile.data.get("company_name", "Your Company") if user_profile.data else "Your Company"
    except Exception:
        company_name = "Your Company"
    st.info(f"🏢 Managing loans for **{company_name}**")

    loans = loans_for_lender(user_id)

    # Toolbar
    t1, t2, t3 = st.columns([1.5, 1, 1])
    with t1:
        if st.button("➕ New Loan"):
            try:
                lender_name = company_name
                new = {
                    "lender_id": user_id,
                    "lender_name": lender_name,
                    "loan_name": f"Loan {len(loans)+1}",   # use loan_name (not name)
                    "principal": 100000.0,
                    "origination_date": date.today().isoformat(),
                    "annual_rate": 5.0,  # percent
                    "term_years": 30,
                    "borrower_name": "To be set",
                   "borrower_email": "to_be_set@example.com",  # Add this line to fix database constraint
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

    sel = st.selectbox(
        "Select Loan",
        options=range(len(loans)),
        format_func=lambda i: f"{(loans[i].get('loan_name') or loans[i].get('name') or 'Loan')} — {loans[i].get('borrower_name','(Borrower?)')} — {loans[i]['id'][:8]}"
    )
    loan = loans[sel]

    # Sidebar: Loan terms incl. Late Fee settings
    with st.sidebar:
        st.header("💰 Loan Terms")
        name_val = loan.get("loan_name") or loan.get("name","")
        name = st.text_input("Loan Name", value=name_val)
        borrower_name = st.text_input("Borrower Name", value=loan.get("borrower_name",""))
        principal = st.number_input("Original Principal ($)", min_value=0.0, value=float(loan.get("principal") or 0.0), step=1000.0, format="%.2f")
        origination_date = st.date_input("Origination Date", value=pd.to_datetime(loan.get("origination_date")).date() if loan.get("origination_date") else date.today())
        annual_rate_pct = st.number_input("Interest Rate (APR %)", min_value=0.0, value=float(loan.get("annual_rate") or 0.0), step=0.1, format="%.3f")
        term_years = st.number_input("Loan Term (years)", min_value=1, value=int(loan.get("term_years") or 30), step=1)

        st.divider()
        st.subheader("Late Fee Rules")
        late_fee_type = st.selectbox("Late Fee Type", ["fixed", "percent"], index=0 if loan.get("late_fee_type") in (None, "fixed") else 1)
        late_fee_amount = st.number_input("Late Fee Amount ($ or %)", min_value=0.0, value=float(loan.get("late_fee_amount") or 0.0), step=1.0, format="%.2f")
        late_fee_days = st.number_input("Grace Period (days)", min_value=0, value=int(loan.get("late_fee_days") or 0), step=1)
        penalty_apr = st.number_input("Penalty Interest APR (%) (optional)", min_value=0.0, value=float(loan.get("penalty_interest_rate") or 0.0), step=0.1, format="%.3f")

        st.divider()
        st.subheader("Borrower link (read-only)")
        st.code(f"?role=borrower&token={loan.get('borrower_token')}", language="text")
        if st.button("Generate New Borrower Token"):
            loan["borrower_token"] = secrets.token_urlsafe(32)
            upsert_loan(loan)
            st.success("New borrower token generated.")

        if st.button("💾 Save Loan"):
            loan.update({
                "loan_name": name,   # save as loan_name
                "borrower_name": borrower_name,
                "principal": principal,
                "origination_date": origination_date.isoformat(),
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
            except Exception as e:
                st.error(f"Save failed: {e}")

        if st.button("🗑️ Delete Loan"):
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

    if not read_only:
        st.subheader("Add New Payment")
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            new_date = st.date_input("Payment Date", value=date.today(), key=f"new_date_{loan_id}")
        with c2:
            new_amount = st.number_input("Amount ($)", min_value=0.01, value=100.00, step=10.0, format="%.2f", key=f"new_amt_{loan_id}")
        with c3:
            if st.button("Add Payment", key=f"addpay_{loan_id}"):
                add = payments_df.copy()
                add = pd.concat([add, pd.DataFrame([{"payment_date": new_date, "amount": new_amount}])], ignore_index=True)
                add = clean_payments_df(add)
                replace_payments(loan_id, add)
                st.success("Payment added.")
                payments_df = payments_for_loan(loan_id)

    label = loan_row.get('loan_name') or loan_row.get('name') or 'Loan'
    st.subheader(f"Ledger — {label} (Late Fees + Penalty Interest) — ACT/365")

    # Compute ledger
    ledger = compute_ledger(
        principal=float(loan_row.get("principal") or 0.0),
        origination_date=pd.to_datetime(loan_row.get("origination_date")).date() if loan_row.get("origination_date") else date.today(),
        annual_rate_decimal=float(loan_row.get("annual_rate") or 0.0) / 100.0,
        payments_df=payments_df.rename(columns={"payment_date": "payment_date", "amount": "amount"}),
        late_fee_type=loan_row.get("late_fee_type", "fixed"),
        late_fee_amount=float(loan_row.get("late_fee_amount") or 0.0),
        late_fee_days=int(loan_row.get("late_fee_days") or 0),
        penalty_apr_decimal=(float(loan_row.get("penalty_interest_rate"))/100.0 if loan_row.get("penalty_interest_rate") else None),
    )

    # Display ledger
    st.dataframe(
        ledger,
        use_container_width=True,
        column_config={
            "Payment Date": st.column_config.DateColumn(format="MM/DD/YYYY", width=110),
            "Due Date": st.column_config.DateColumn(format="MM/DD/YYYY", width=110),
            "Payment Amount": st.column_config.NumberColumn(format="$%.2f"),
            "Accrued Loan Interest": st.column_config.NumberColumn(format="$%.2f"),
            "Penalty Interest Accrued": st.column_config.NumberColumn(format="$%.2f"),
            "Late Fee (Assessed)": st.column_config.NumberColumn(format="$%.2f"),
            "Allocated → Penalty Interest": st.column_config.NumberColumn(format="$%.2f"),
            "Allocated → Late Fees": st.column_config.NumberColumn(format="$%.2f"),
            "Allocated → Loan Interest": st.column_config.NumberColumn(format="$%.2f"),
            "Allocated → Principal": st.column_config.NumberColumn(format="$%.2f"),
            "Principal Balance (End)": st.column_config.NumberColumn(format="$%.2f"),
            "Late Fees Outstanding (End)": st.column_config.NumberColumn(format="$%.2f"),
            "Penalty Interest Outstanding (End)": st.column_config.NumberColumn(format="$%.2f"),
        },
        hide_index=True,
        height=420
    )

    # Metrics (current status)
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
    if not SUPABASE_OK:
        st.error("⚠️ Supabase connection failed. Check secrets configuration.")
        st.stop()

    # Handle Supabase redirect tokens (magic link / oauth)
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

    # Borrower via token (no auth)
    if role_hint == "borrower" and token:
        borrower_view_by_token(token)
        return

    # Signed-in flows
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

    # Otherwise landing
    landing()


if __name__ == "__main__":
    main()