import streamlit as st
st.set_page_config(page_title="Loan Payment Calculator", page_icon="💸", layout="centered")

import os
import json
import secrets
from io import BytesIO
from datetime import date, datetime, timedelta

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# ---------------------------
# Supabase client
# ---------------------------
try:
    from supabase import create_client, Client
    # Support both mapping and attribute access for secrets
    _sb = st.secrets.get("supabase", {})
    SUPABASE_URL = _sb.get("url") or getattr(getattr(st.secrets, "supabase", {}), "url", None)
    SUPABASE_ANON_KEY = _sb.get("anon_key") or getattr(getattr(st.secrets, "supabase", {}), "anon_key", None)
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("Missing supabase.url or supabase.anon_key in Streamlit secrets.")
    
    # Create client with positional parameters for v1.2.0 compatibility
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    SUPABASE_OK = True
except Exception as e:
    SUPABASE_OK = False
    supabase = None
    st.error(f"Supabase init failed: {e}")

# ---------------------------
# Helpers: auth + role routing
# ---------------------------
def get_session():
    """Return current Supabase session (or None)."""
    if not SUPABASE_OK:
        return None
    try:
        res = supabase.auth.get_session()
        return res
    except Exception:
        return None

def sign_out():
    if not SUPABASE_OK:
        return
    try:
        supabase.auth.sign_out()
        # Clear all session state
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.success("✅ Successfully signed out")
    except Exception as e:
        st.error(f"Sign out error: {e}")

def oauth_button(provider: str, label: str):
    if st.button(label, use_container_width=True):
        # Set the redirect URL to our Streamlit app
        redirect_to = "http://localhost:8501"
        try:
            auth_res = supabase.auth.sign_in_with_oauth(
                {"provider": provider, "options": {"redirect_to": redirect_to}}
            )
            st.markdown(f"[Continue with {provider.title()} →]({auth_res.url})", unsafe_allow_html=True)
        except Exception as e:
            st.error(f"OAuth error: {e}")

def ensure_session_in_state():
    if not SUPABASE_OK:
        return
    if "session" not in st.session_state:
        sess = get_session()
        if sess and getattr(sess, "session", None):
            st.session_state["session"] = sess.session

def role_from_query() -> str | None:
    """Optional role hint from landing selection."""
    qp = st.query_params
    return (qp.get("role", None) or st.session_state.get("role") or None)

def borrower_token_from_query() -> str | None:
    qp = st.query_params
    return qp.get("token", None)

def set_role_in_url(role: str):
    st.session_state["role"] = role
    st.query_params["role"] = role

# ---------------------------
# DB access
# ---------------------------
def loans_for_lender(user_id: str) -> list[dict]:
    data = supabase.table("loans").select("*").eq("lender_id", user_id).order("created_at").execute().data
    return data or []

def loans_for_borrower_signed_in(user_id: str) -> list[dict]:
    """If loan_borrowers exists, use it; else return empty (we'll fall back to token)."""
    try:
        # If table doesn't exist, this will raise
        data = supabase.rpc("sql", {}).execute()  # cheap ping
        # Do join directly
        q = supabase.from_("loans").select(
            "id,name,principal,origination_date,annual_rate,term_years,borrower_name,borrower_token,created_at"
        ).in_("id",
            supabase.table("loan_borrowers").select("loan_id").eq("user_id", user_id).execute().data or []
        )
        # The supabase-py client doesn't support subselect nicely; fallback to RPC below if join table exists:
        # Try simple select to detect table
        supabase.table("loan_borrowers").select("loan_id").limit(1).execute()
        # Implement join by two calls:
        lb = supabase.table("loan_borrowers").select("loan_id").eq("user_id", user_id).execute().data or []
        loan_ids = [row["loan_id"] for row in lb]
        if not loan_ids:
            return []
        loans = supabase.table("loans").select("*").in_("id", loan_ids).order("created_at").execute().data
        return loans or []
    except Exception:
        return []  # no join table; rely on token

def loans_for_borrower_by_token(token: str) -> list[dict]:
    if not token:
        return []
    data = supabase.table("loans").select("*").eq("borrower_token", token).limit(1).execute().data
    return data or []

def payments_for_loan(loan_id: str) -> pd.DataFrame:
    rows = supabase.table("payments").select("*").eq("loan_id", loan_id).order("payment_date").execute().data or []
    if not rows:
        return pd.DataFrame(columns=["payment_date", "amount"])
    df = pd.DataFrame(rows)
    df["payment_date"] = pd.to_datetime(df["payment_date"], errors="coerce").dt.date
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df[["payment_date", "amount"]]

def upsert_loan(loan: dict):
    return supabase.table("loans").upsert(loan, on_conflict="id").execute()

def delete_loan(loan_id: str):
    return supabase.table("loans").delete().eq("id", loan_id).execute()

def replace_payments(loan_id: str, df: pd.DataFrame):
    # delete + bulk insert for simplicity (RLS ensures only owner can write)
    supabase.table("payments").delete().eq("loan_id", loan_id).execute()
    if df is None or df.empty:
        return
    payload = []
    for _, r in df.iterrows():
        payload.append({
            "loan_id": loan_id,
            "payment_date": pd.to_datetime(r["payment_date"]).date().isoformat(),
            "amount": float(r["amount"]),
        })
    # bulk upsert
    supabase.table("payments").insert(payload).execute()

# ---------------------------
# Data cleaning & calc
# ---------------------------
def clean_payments_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["payment_date", "amount"])
    out = df.copy()
    # normalize columns
    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
    # map common names
    if "date" in out.columns and "payment_date" not in out.columns:
        out = out.rename(columns={"date": "payment_date"})
    if "amount" not in out.columns:
        raise ValueError("Missing 'Amount' column")
    # strip and parse
    out["payment_date"] = pd.to_datetime(out["payment_date"], errors="coerce").dt.date
    amt = out["amount"].astype(str).str.strip()
    amt = amt.str.replace(r"^\((.*)\)$", r"-\1", regex=True).str.replace(",", "", regex=False).str.replace("$", "", regex=False).str.replace("\u00A0", "", regex=False)
    out["amount"] = pd.to_numeric(amt, errors="coerce")
    out = out.dropna(subset=["payment_date", "amount"]).reset_index(drop=True)
    out = out[out["amount"] != 0]
    return out[["payment_date", "amount"]]

def compute_schedule(principal, origination_date, annual_rate_decimal, payments_df):
    df = clean_payments_df(payments_df.rename(columns={"Date": "payment_date", "Amount": "amount"})) if set(payments_df.columns) != {"payment_date", "amount"} else clean_payments_df(payments_df)
    df = df[df["payment_date"] >= origination_date]
    df = df.sort_values("payment_date")

    schedule = []
    bal = round(float(principal), 2)
    last_date = origination_date
    accrued_carry = 0.0

    for _, row in df.iterrows():
        d = row["payment_date"]
        amt = float(row["amount"])
        days = (d - last_date).days
        interest_accrued = bal * annual_rate_decimal * (days / 365.0) if days > 0 else 0.0
        interest_due = interest_accrued + accrued_carry

        if amt >= interest_due:
            interest_applied = round(interest_due, 2)
            principal_applied = round(amt - interest_due, 2)
            bal = round(bal - principal_applied, 2)
            accrued_carry = 0.0
        else:
            interest_applied = round(amt, 2)
            principal_applied = 0.0
            accrued_carry = round(interest_due - amt, 2)

        schedule.append({
            "Payment Date": d,
            "Days Since Last Payment": days,
            "Payment Amount": round(amt, 2),
            "Interest Accrued Since Last Payment": round(interest_accrued, 2),
            "Interest Applied": interest_applied,
            "Principal Applied": principal_applied,
            "Principal Balance After Payment": bal
        })
        last_date = d

    return pd.DataFrame(schedule)

def build_pdf(df, principal, origination_date, annual_rate_decimal, term_years):
    buf = BytesIO()
    pp = PdfPages(buf)

    # Summary page
    fig = plt.figure(figsize=(8.5, 11))
    fig.clf()
    r = annual_rate_decimal / 12.0
    n = int(term_years * 12)
    ref_payment = 0.0 if r <= 0 or n <= 0 else round(principal * r / (1 - (1 + r) ** (-n)), 2)

    summary = f"""\
Loan Payment Report
Generated: {date.today():%B %d, %Y}

Original Principal: ${principal:,.2f}
Origination Date: {origination_date:%B %d, %Y}
Interest Rate: {annual_rate_decimal*100:.3f}% APR (Actual/365 simple interest)
Loan Term: {term_years} years

Reference Monthly Payment (level-pay): ${ref_payment:,.2f}

Total Payments: {len(df)}
Total Interest Applied: ${df['Interest Applied'].sum():,.2f}
Total Principal Applied: ${df['Principal Applied'].sum():,.2f}
Remaining Principal: ${df['Principal Balance After Payment'].iloc[-1]:,.2f}
"""
    import textwrap
    wrapped = "\n".join([textwrap.fill(line, width=90) for line in summary.strip().splitlines()])
    plt.axis('off')
    plt.text(0.05, 0.95, wrapped, va='top', ha='left', fontsize=10, family='monospace')
    pp.savefig(fig)
    plt.close(fig)

    # Per-payment table pages
    cols = ["Payment Date", "Payment Amount", "Days Since Last Payment",
            "Interest Accrued Since Last Payment", "Interest Applied",
            "Principal Applied", "Principal Balance After Payment"]
    dfp = df.copy()
    dfp["Payment Date"] = pd.to_datetime(dfp["Payment Date"]).dt.strftime("%Y-%m-%d")
    rows_per_page = 25
    for start in range(0, len(dfp), rows_per_page):
        chunk = dfp.iloc[start:start + rows_per_page][cols]
        fig = plt.figure(figsize=(8.5, 11))
        ax = fig.add_subplot(111)
        ax.axis('off')
        tbl = ax.table(cellText=chunk.values, colLabels=chunk.columns, loc='center')
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8)
        tbl.scale(1, 1.2)
        ax.set_title("Per-Payment Allocation", fontsize=12, pad=20)
        pp.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    pp.close()
    buf.seek(0)
    return buf.getvalue()

# ---------------------------
# UI blocks
# ---------------------------
def landing():
    st.title("Welcome")
    st.write("Choose how you want to continue:")
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
    
    # Add explanations
    st.info("""
    **Authentication Options:**
    - **Sign Up**: Create a new account (requires email confirmation)
    - **Sign In**: Use existing email/password
    - **Magic Link**: Passwordless sign-in via email link
    - **Google OAuth**: Sign in with your Google account
    """)
    
    with st.expander("Email & Password", expanded=True):
        email = st.text_input("Email")
        pw = st.text_input("Password", type="password")
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            if st.button("Sign Up", use_container_width=True, key="signup_btn"):
                if not email or not pw:
                    st.error("Please enter both email and password.")
                    return
                try:
                    # Sign up the user with explicit redirect
                    result = supabase.auth.sign_up({
                        "email": email, 
                        "password": pw,
                        "options": {
                            "email_redirect_to": "http://localhost:8501",
                            "data": {
                                "redirect_to": "http://localhost:8501"
                            }
                        }
                    })
                    
                    if result.user:
                        st.success(f"✅ Signup successful! Check your email ({email}) to confirm your account.")
                        st.info("After confirming your email, you can sign in with the same credentials.")
                    else:
                        st.warning("Signup initiated. Please check your email for confirmation.")
                        
                except Exception as e:
                    st.error(f"Signup error: {e}")
                    st.info("Make sure your password is at least 6 characters long.")
        with cc2:
            if st.button("Sign In", use_container_width=True, key="signin_btn"):
                if not email or not pw:
                    st.error("Please enter both email and password.")
                    return
                try:
                    res = supabase.auth.sign_in_with_password({
                        "email": email, 
                        "password": pw
                    })
                    st.session_state["session"] = res.session
                    st.success(f"✅ Signed in as {email}!")
                    
                    # Try to create a profile if it doesn't exist
                    try:
                        user_id = res.user.id
                        # Check if profile exists
                        existing_profile = supabase.table("profiles").select("id").eq("id", user_id).execute()
                        if not existing_profile.data:
                            # Create a new profile
                            profile_data = {
                                "id": user_id,
                                "email": email,
                                "company_name": "Your Company",
                                "created_at": datetime.now().isoformat()
                            }
                            supabase.table("profiles").insert(profile_data).execute()
                            st.info("Profile created successfully!")
                        
                        # Check if this user is a borrower on any loans
                        try:
                            borrower_loans = supabase.table("loans").select("id,name").eq("borrower_name", email).execute().data or []
                            if borrower_loans:
                                st.success(f"Found {len(borrower_loans)} loan(s) linked to your email!")
                                st.info("You can now view these loans in borrower mode.")
                        except Exception as loan_error:
                            pass  # Ignore loan linking errors
                            
                    except Exception as profile_error:
                        st.warning(f"Profile creation failed: {profile_error}")
                    
                    st.rerun()
                except Exception as e:
                    st.error(f"Sign in error: {e}")
                    st.info("Make sure your email is confirmed and password is correct.")
        with cc3:
            if st.button("Magic Link", use_container_width=True, key="magic_btn"):
                if not email:
                    st.error("Please enter your email address.")
                    return
                try:
                    # Send a magic link (passwordless sign-in)
                    supabase.auth.sign_in_with_otp({
                        "email": email, 
                        "options": {
                            "email_redirect_to": "http://localhost:8501"
                        }
                    })
                    st.success(f"✅ Magic link sent to {email}!")
                    st.info("Click the link in your email to sign in without a password.")
                except Exception as e:
                    st.error(f"Magic link error: {e}")

    st.subheader("Or continue with")
    st.info("💡 **Google OAuth not configured** - Enable in Supabase Dashboard → Authentication → Providers")
    # oauth_button("google", "Continue with Google")
    # Uncomment if you’ve configured Apple in Supabase
    # oauth_button("apple", "Continue with Apple")

def borrower_view_by_token(token: str):
    rows = loans_for_borrower_by_token(token)
    if not rows:
        st.error("Invalid or expired borrower link.")
        return
    loan = rows[0]
    st.title(f"📋 Loan Statement — {loan['name']}")
    _common_loan_view(loan, read_only=True)

def borrower_view_signed_in(user_id: str):
    rows = loans_for_borrower_signed_in(user_id)
    st.title("📋 Your Loans (Borrower)")
    if not rows:
        st.info("No loans are shared with this account.")
        return
    names = [f"{r['name']} — {r['id'][:8]}" for r in rows]
    idx = st.selectbox("Select loan", range(len(rows)), format_func=lambda i: names[i])
    loan = rows[idx]
    _common_loan_view(loan, read_only=True)

def lender_view(user_id: str):
    st.title("💸 Loan Payment Calculator & Report")
    st.caption("Irregular payments • Actual/365 simple interest • Interest first, then principal • No compounding unpaid interest")

    # Get user profile to show company name
    try:
        user_profile = supabase.table("profiles").select("company_name").eq("id", user_id).single().execute()
        company_name = user_profile.data.get("company_name", "Your Company") if user_profile.data else "Your Company"
    except:
        company_name = "Your Company"
    
    st.info(f"🏢 Managing loans for: **{company_name}**")

    loans = loans_for_lender(user_id)
    # Toolbar
    t1, t2, t3, t4 = st.columns([1.5, 1, 1, 1])
    with t1:
        if st.button("➕ New Loan"):
            # Get lender's name from profile
            try:
                lender_profile = supabase.table("profiles").select("name").eq("id", user_id).single().execute()
                lender_name = lender_profile.data.get("name", "Unknown Lender") if lender_profile.data else "Unknown Lender"
            except:
                lender_name = "Unknown Lender"
            
            # For new loans, we'll set borrower info after creation
            new = {
                "lender_id": user_id,
                "lender_name": lender_name,
                "name": f"Loan {len(loans)+1}",
                "principal": 100000.0,
                "origination_date": date.today().isoformat(),
                "annual_rate": 5.0,  # percent
                "term_years": 30,
                "borrower_name": "To be set",  # Will be updated after creation
            }
            upsert_loan(new)
            st.rerun()
    with t2:
        if st.button("🔄 Refresh"):
            st.rerun()
    with t3:
        if st.button("🚪 Sign out", key="signout_lender"):
            sign_out()
            st.rerun()
    with t4:
        st.write("")

    if not loans:
        st.info("No loans yet. Click **New Loan** to create one.")
        return

    sel = st.selectbox(
        "Select Loan",
        options=range(len(loans)),
        format_func=lambda i: f"{loans[i]['name']} — {loans[i].get('borrower_name', 'Unknown Borrower')} — {loans[i]['id'][:8]}"
    )
    loan = loans[sel]

    # Loan details (editable)
    with st.sidebar:
        st.header("💰 Loan Terms")
        name = st.text_input("Loan Name", value=loan["name"])
        
        # Borrower selection: existing users or manual entry
        st.subheader("Borrower")
        
        # Get list of existing users for dropdown
        try:
            existing_users = supabase.table("profiles").select("id,name,email").execute().data or []
            existing_user_names = [user["name"] for user in existing_users if user["name"]]
            
            if existing_user_names:
                borrower_option = st.radio(
                    "Borrower Type:",
                    ["Select from registered users", "Enter new borrower manually"],
                    key=f"borrower_type_{loan['id']}"
                )
                
                if borrower_option == "Select from registered users":
                    selected_user_name = st.selectbox(
                        "Select Borrower:",
                        existing_user_names,
                        key=f"existing_borrower_{loan['id']}"
                    )
                    borrower_name = selected_user_name
                    # Find the selected user's ID for linking
                    selected_user = next((u for u in existing_users if u["name"] == selected_user_name), None)
                    if selected_user:
                        loan["borrower_user_id"] = selected_user["id"]
                else:
                    borrower_name = st.text_input("New Borrower Name:", value=loan.get("borrower_name", ""))
                    loan["borrower_user_id"] = None
            else:
                borrower_name = st.text_input("Borrower Name:", value=loan.get("borrower_name", ""))
                loan["borrower_user_id"] = None
        except Exception as e:
            borrower_name = st.text_input("Borrower Name:", value=loan.get("borrower_name", ""))
            loan["borrower_user_id"] = None
        
        principal = st.number_input("Original Principal ($)", min_value=0.0, value=float(loan["principal"]), step=1000.0, format="%.2f")
        origination_date = st.date_input("Origination Date", value=pd.to_datetime(loan["origination_date"]).date())
        annual_rate_pct = st.number_input("Interest Rate (APR %)", min_value=0.0, value=float(loan["annual_rate"]), step=0.1, format="%.3f")
        term_years = st.number_input("Loan Term (years)", min_value=1, value=int(loan["term_years"]), step=1)
        st.divider()
        st.subheader("Borrower link")
        st.caption("Read-only borrower portal:")
        st.code(f"?role=borrower&token={loan.get('borrower_token')}", language="text")
        if st.button("Generate New Borrower Token"):
            loan["borrower_token"] = secrets.token_urlsafe(32)
            upsert_loan(loan)
            st.success("New borrower token generated.")

        if st.button("💾 Save Loan"):
            loan.update({
                "name": name,
                "borrower_name": borrower_name,
                "principal": principal,
                "origination_date": origination_date.isoformat(),
                "annual_rate": annual_rate_pct,
                "term_years": term_years,
            })
            upsert_loan(loan)
            st.success("Saved.")

        if st.button("🗑️ Delete Loan"):
            delete_loan(loan["id"])
            st.warning("Loan deleted.")
            st.rerun()

    _common_loan_view(loan, read_only=False)

def _common_loan_view(loan_row: dict, read_only: bool):
    # Load payments from DB
    loan_id = loan_row["id"]
    payments_df = payments_for_loan(loan_id)

    st.subheader("Payments")
    st.caption("Upload a CSV with columns: Date, Amount (or Payment Date, Amount). Positive amounts = payments.")

    # CSV upload
    uploaded = st.file_uploader("Upload payments CSV (optional)", type=["csv"], disabled=read_only)
    if uploaded is not None and not read_only:
        try:
            tmp = pd.read_csv(uploaded, dtype=str, keep_default_na=False)
            # try to normalize
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

    # Manual add (lender only)
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

    # Editable grid (lender), or read-only (borrower)
    st.subheader("Payment History")
    grid = st.data_editor(
        payments_df.rename(columns={"payment_date": "Date", "amount": "Amount"}),
        num_rows="dynamic" if not read_only else "fixed",
        disabled=read_only,
        use_container_width=True,
        height=360
    )
    if not read_only and not grid.equals(payments_df.rename(columns={"payment_date": "Date", "amount": "Amount"})):
        # save edits
        cleaned = clean_payments_df(grid.rename(columns={"Date": "payment_date", "Amount": "amount"}))
        replace_payments(loan_id, cleaned)
        st.success("Saved changes.")
        payments_df = payments_for_loan(loan_id)

    # Calculate & show schedule
    st.subheader("Amortization (Actual/365 Simple Interest)")
    if st.button("Calculate & Show Tables", type="primary", key=f"calc_{loan_id}"):
        df = compute_schedule(
            principal=float(loan_row["principal"]),
            origination_date=pd.to_datetime(loan_row["origination_date"]).date(),
            annual_rate_decimal=float(loan_row["annual_rate"]) / 100.0,
            payments_df=payments_df.rename(columns={"payment_date": "Date", "amount": "Amount"})
        )
        if df.empty:
            st.warning("No payments on/after origination date.")
        else:
            st.dataframe(
                df,
                use_container_width=True,
                column_config={
                    "Payment Date": st.column_config.DateColumn("Payment Date", format="MM/DD/YYYY", width=110),
                    "Days Since Last Payment": st.column_config.NumberColumn("Days Since Last Payment", format="%d", width=150),
                    "Payment Amount": st.column_config.NumberColumn("Payment Amount", format="$%.2f", width=130),
                    "Interest Accrued Since Last Payment": st.column_config.NumberColumn("Interest Accrued Since Last Payment", format="$%.2f", width=180),
                    "Interest Applied": st.column_config.NumberColumn("Interest Applied", format="$%.2f", width=130),
                    "Principal Applied": st.column_config.NumberColumn("Principal Applied", format="$%.2f", width=130),
                    "Principal Balance After Payment": st.column_config.NumberColumn("Principal Balance After Payment", format="$%.2f", width=190),
                },
                hide_index=True
            )

            # Current status
            last_payment_date = df["Payment Date"].max()
            last_balance = df["Principal Balance After Payment"].iloc[-1]
            days_since = (date.today() - last_payment_date).days if pd.notna(last_payment_date) else 0
            if days_since > 0:
                rate = float(loan_row["annual_rate"]) / 100.0
                accrued = last_balance * rate * (days_since / 365.0)
                c1, c2, c3 = st.columns(3)
                c1.metric("Days Since Last Payment", days_since)
                c2.metric("Current Principal Balance", f"${last_balance:,.2f}")
                c3.metric("Interest Accrued Since Last Payment", f"${accrued:,.2f}")
                st.info(f"Interest accrues daily at {rate*100:.3f}% APR on ${last_balance:,.2f}.")

            # PDF download
            if st.button("Generate PDF Report", key=f"pdf_{loan_id}"):
                pdf_bytes = build_pdf(
                    df,
                    principal=float(loan_row["principal"]),
                    origination_date=pd.to_datetime(loan_row["origination_date"]).date(),
                    annual_rate_decimal=float(loan_row["annual_rate"]) / 100.0,
                    term_years=int(loan_row["term_years"])
                )
                fname = f"loan_report_{loan_row['name'].replace(' ','_')}_{date.today().isoformat()}.pdf"
                st.download_button("Download PDF", data=pdf_bytes, file_name=fname, mime="application/pdf")

# ---------------------------
# App entry
# ---------------------------
def main():
    if not SUPABASE_OK:
        st.error("⚠️ Supabase connection failed. Please check your configuration.")
        st.stop()

    # Check if we're coming from a Supabase redirect
    query_params = st.query_params
    if "access_token" in query_params or "refresh_token" in query_params:
        st.info("🔄 Processing authentication... Please wait.")
        try:
            # Force a session refresh to capture the new tokens
            if "session" in st.session_state:
                del st.session_state["session"]
            ensure_session_in_state()
            st.rerun()
        except Exception as e:
            st.error(f"Authentication processing failed: {e}")

    ensure_session_in_state()
    session = st.session_state.get("session")
    token = borrower_token_from_query()
    role_hint = role_from_query()

    # Borrower via token link (no auth required; read-only)
    if role_hint == "borrower" and token:
        borrower_view_by_token(token)
        return

    # If signed in:
    if session and session.user:
        uid = session.user.id
        with st.sidebar:
            st.success(f"✅ Signed in as: {session.user.email or uid}")
            if st.button("🚪 Sign out", key="signout_main"):
                sign_out()
                st.rerun()

        # If user chose borrower role (and you have a join table), show borrower-view; else lender-view
        if role_hint == "borrower":
            borrower_view_signed_in(uid)
        else:
            lender_view(uid)
        return

    # Not signed in and no borrower token → landing
    landing()

if __name__ == "__main__":
    main()
