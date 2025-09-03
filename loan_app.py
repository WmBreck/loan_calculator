import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
from io import BytesIO
import numpy as np

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import json
import os

# Persistent storage functions
def _to_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    out = df.copy()
    # ensure JSON-friendly types
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce").dt.date.astype(str)
    out["Amount"] = pd.to_numeric(out["Amount"], errors="coerce")
    return out.to_dict("records")

def save_data():
    data_to_save = {
        "loans": {},
        "current_loan": st.session_state.current_loan
    }
    for name, loan in st.session_state.loans.items():
        data_to_save["loans"][name] = {
            "principal": float(loan["principal"]),
            # store as ISO date string
            "origination_date": str(loan["origination_date"]),
            # store as numeric percentage
            "annual_rate": float(loan["annual_rate"]),
            "term_years": int(loan["term_years"]),
            "payments_df": _to_records(loan.get("payments_df", pd.DataFrame(columns=["Date","Amount"])))
        }
    with open("loan_data.json", "w") as f:
        json.dump(data_to_save, f, indent=2)

def load_data():
    if not os.path.exists("loan_data.json"):
        return None
    try:
        with open("loan_data.json", "r") as f:
            data = json.load(f)

        # restore types
        for name, loan in data["loans"].items():
            # origination_date back to date
            od = pd.to_datetime(loan.get("origination_date"), errors="coerce")
            loan["origination_date"] = od.date() if od is not None and not pd.isna(od) else date.today()

            # ensure numerics
            loan["principal"] = float(loan.get("principal", 0))
            loan["annual_rate"] = float(loan.get("annual_rate", 0))  # still stored as percent
            loan["term_years"] = int(loan.get("term_years", 1))

            # payments dataframe
            rows = loan.get("payments_df", [])
            if rows:
                df = pd.DataFrame(rows)
                df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
                df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
                loan["payments_df"] = df.dropna(subset=["Date","Amount"]).reset_index(drop=True)
            else:
                loan["payments_df"] = pd.DataFrame(columns=["Date", "Amount"])

        return data
    except Exception as e:
        st.error(f"Error loading saved data: {e}")
        return None

# ============================================================================
# CRITICAL SECTION: App Configuration and Validation
# ============================================================================
# DO NOT MODIFY THIS SECTION WITHOUT UPDATING FEATURE_CHECKLIST.md
# ============================================================================

st.set_page_config(page_title="Loan Payment Calculator", page_icon="💸", layout="centered")

# Feature validation function
def validate_critical_features():
    """Validate that all critical features are present and working"""
    critical_features = [
        "compute_schedule",
        "build_pdf", 
        "save_data",
        "load_data"
    ]
    
    missing_features = []
    for feature in critical_features:
        if feature not in globals():
            missing_features.append(feature)
    
    if missing_features:
        st.error(f"🚨 CRITICAL ERROR: Missing functions: {missing_features}")
        st.error("This indicates critical functionality has been accidentally removed!")
        st.error("Please restore from git or contact developer immediately.")
        return False
    
    return True

st.title("💸 Loan Payment Calculator & Report")

st.markdown("""
This tool calculates interest and principal allocation for **irregular payments** using **Actual/365 simple interest**.
- Interest accrues daily on principal only.
- Each payment is applied to **accrued interest first**, then to principal.
- Unpaid interest (if any) is carried but **does not compound**.
- Export a dated PDF report for sharing.
""")

# ============================================================================
# CRITICAL SECTION: Multi-loan Management System
# ============================================================================
# DO NOT MODIFY THIS SECTION WITHOUT UPDATING FEATURE_CHECKLIST.md
# This section handles loan creation, selection, and persistence
# ============================================================================

# Multi-loan management
if "loans" not in st.session_state:
    # Try to load saved data first
    saved_data = load_data()
    if saved_data:
        st.session_state.loans = saved_data["loans"]
        st.session_state.current_loan = saved_data["current_loan"]
    else:
        # Default loan if no saved data
        st.session_state.loans = {
            "Loan to Beth": {
                "principal": 216000.0,
                "origination_date": date(2023, 8, 31),
                "annual_rate": 5.0,
                "term_years": 15,
                "payments_df": pd.DataFrame(columns=["Date", "Amount"])
            }
        }
        st.session_state.current_loan = "Loan to Beth"

# Loan selection and management
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    current_loan = st.selectbox(
        "Select Loan",
        options=list(st.session_state.loans.keys()),
        key="loan_selector"
    )
    st.session_state.current_loan = current_loan
    
    # Loan renaming feature
    with st.expander("Rename Loan"):
        new_name = st.text_input(
            "New Loan Name",
            value=current_loan,
            placeholder="e.g., Loan to Beth, Home Renovation, etc.",
            key="rename_input"
        )
        if st.button("Rename Loan", key="rename_button"):
            if new_name and new_name != current_loan and new_name.strip():
                # Rename the loan in the session state
                loan_data = st.session_state.loans[current_loan]
                del st.session_state.loans[current_loan]
                st.session_state.loans[new_name] = loan_data
                st.session_state.current_loan = new_name
                save_data()
                st.rerun()
            elif not new_name.strip():
                st.error("Loan name cannot be empty")
            else:
                st.info("No changes made")

with col2:
    if st.button("Add New Loan"):
        loan_num = len(st.session_state.loans) + 1
        new_loan_name = f"Loan {loan_num}"
        st.session_state.loans[new_loan_name] = {
            "principal": 100000.0,
            "origination_date": date.today(),
            "annual_rate": 5.0,
            "term_years": 30,
            "payments_df": pd.DataFrame(columns=["Date", "Amount"])
        }
        st.session_state.current_loan = new_loan_name
        save_data()
        st.rerun()

with col3:
    if len(st.session_state.loans) > 1:
        if st.button("Delete Current Loan"):
            del st.session_state.loans[current_loan]
            st.session_state.current_loan = list(st.session_state.loans.keys())[0]
            save_data()
            st.rerun()

# Get current loan data
current_loan_data = st.session_state.loans[current_loan]

# Debug mode toggle (for administrators)
st.session_state.show_debug = st.checkbox("🔧 Display Debugging Information", value=st.session_state.get("show_debug", False), key="debug_toggle")

if st.session_state.get("show_debug", False):
    st.success("🔧 Debug mode: ON")
    st.info("Debug information will be displayed below when processing payments.")
else:
    st.info("🔧 Debug mode: OFF - Check the box above to enable debugging information.")

with st.sidebar:
    st.header("Loan Terms")
    principal = st.number_input("Original Principal ($)", min_value=0.0, value=current_loan_data["principal"], step=1000.0, format="%.2f")
    origination_date = st.date_input("Origination Date", value=current_loan_data["origination_date"])
    annual_rate = st.number_input("Interest Rate (APR %)", min_value=0.0, value=current_loan_data["annual_rate"], step=0.1, format="%.3f") / 100.0
    term_years = st.number_input("Loan Term (years)", min_value=1, value=current_loan_data["term_years"], step=1)
    
    # Update loan data when sidebar values change
    current_loan_data.update({
        "principal": principal,
        "origination_date": origination_date,
        "annual_rate": annual_rate * 100,  # Store as percentage
        "term_years": term_years
    })
    save_data()

st.subheader("Payments")
st.caption("Enter payments below or upload a CSV with columns: Date, Amount. Positive amounts = payments.")

uploaded = st.file_uploader("Upload payments CSV (optional)", type=["csv"])

if uploaded is not None:
    try:
        tmp = pd.read_csv(uploaded, dtype=str, keep_default_na=False)
        # normalize columns
        date_col = None
        amt_col = None
        for c in tmp.columns:
            cl = str(c).strip().lower()
            if "date" in cl and date_col is None:
                date_col = c
            if ("amount" in cl or "amt" in cl) and amt_col is None:
                amt_col = c
        if date_col is None or amt_col is None:
            st.error("Could not find 'Date' and 'Amount' columns.")
        else:
            tmp = tmp[[date_col, amt_col]].rename(columns={date_col: "Date", amt_col: "Amount"})
            current_loan_data["payments_df"] = tmp
            save_data()
    except Exception as e:
        st.error(f"Failed to parse CSV: {e}")

# Manual payment entry
st.subheader("Add New Payment")
col1, col2 = st.columns(2)
with col1:
    new_payment_date = st.date_input("Payment Date", value=date.today(), key="new_payment_date")
with col2:
    new_payment_amount = st.number_input("Payment Amount ($)", min_value=0.01, value=100.0, step=10.0, format="%.2f", key="new_payment_amount")

if st.button("Enter New Payment", type="primary"):
    # Input validation
    if new_payment_amount <= 0:
        st.error("❌ Payment amount must be greater than $0.00")
    elif new_payment_date < current_loan_data["origination_date"]:
        st.error(f"❌ Payment date cannot be before loan origination date ({current_loan_data['origination_date'].strftime('%m/%d/%Y')})")
    else:
        # Create new payment row
        new_payment = pd.DataFrame({
            "Date": [new_payment_date],
            "Amount": [new_payment_amount]
        })
        
        # Ensure we have a DataFrame for the current payments
        payments_df = current_loan_data["payments_df"]
        if isinstance(payments_df, list):
            payments_df = pd.DataFrame(payments_df) if payments_df else pd.DataFrame(columns=["Date", "Amount"])
        
        # Add new payment and sort by date
        payments_df = pd.concat([payments_df, new_payment], ignore_index=True)
        payments_df = payments_df.sort_values("Date").reset_index(drop=True)
        
        # Update the loan data
        current_loan_data["payments_df"] = payments_df
        save_data()
        
        st.success(f"✅ Added payment of ${new_payment_amount:.2f} on {new_payment_date.strftime('%m/%d/%Y')}")
        
        # Auto-recalculate the schedule
        st.rerun()

st.subheader("Payment History")
st.caption("Edit payments below or use the CSV upload above to add multiple payments at once.")

# Display and edit payments for current loan
# Ensure we have a DataFrame for the data editor
payments_df = current_loan_data["payments_df"]
if isinstance(payments_df, list):
    payments_df = pd.DataFrame(payments_df) if payments_df else pd.DataFrame(columns=["Date", "Amount"])
    current_loan_data["payments_df"] = payments_df

edited_df = st.data_editor(
    payments_df, 
    num_rows="dynamic", 
    width='stretch', 
    height=320
)

# Check if payments were edited and save if changed
if not edited_df.equals(payments_df):
    current_loan_data["payments_df"] = edited_df
    save_data()
    st.success("✅ Payment changes saved!")

# ============================================================================
# CRITICAL FUNCTION: Core Calculation Engine
# ============================================================================
# DO NOT MODIFY THIS FUNCTION WITHOUT UPDATING FEATURE_CHECKLIST.md
# This function contains the Actual/365 interest calculation logic
# and payment allocation algorithm - core business logic
# ============================================================================

def compute_schedule(principal, origination_date, annual_rate, payments_df):
    df = payments_df.copy()

    # ---- DEBUG (conditional display) ----
    if st.session_state.get("show_debug", False):
        st.text(f"Debug - Original payments count: {len(df)}")
        if not df.empty:
            st.write("Debug - Original payments (head):", df.head())

    # --- Normalize column names just in case ---
    df.columns = [str(c).strip() for c in df.columns]

    # --- Trim and normalize values ---
    # Date: keep as string first
    df["Date"] = df["Date"].astype(str).str.strip()

    # Amount: remove currency formatting: commas, $; handle parentheses as negatives; trim spaces
    amt = df["Amount"].astype(str).str.strip()
    # Convert '(1,234.56)' -> '-1234.56'
    amt = amt.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    amt = amt.str.replace(",", "", regex=False).str.replace("$", "", regex=False)
    # Some CSVs may carry stray non-breaking spaces or weird unicode
    amt = amt.str.replace("\u00A0", "", regex=False)
    df["Amount"] = pd.to_numeric(amt, errors="coerce")

    # --- Parse dates flexibly ---
    # Try common US formats first, including 2-digit years
    d1 = pd.to_datetime(df["Date"], format="%m/%d/%Y", errors="coerce")
    d2 = pd.to_datetime(df["Date"], format="%m/%d/%y",  errors="coerce")
    # Where d1 is NaT, fill from d2; otherwise keep d1
    date_series = d1.fillna(d2)
    # Final fallback: generic parser
    date_series = date_series.fillna(pd.to_datetime(df["Date"], errors="coerce"))

    df["Date"] = date_series.dt.date

    # --- Drop rows with missing essentials ---
    before = len(df)
    df = df.dropna(subset=["Date", "Amount"])
    after = len(df)
    if st.session_state.get("show_debug", False):
        st.text(f"Debug - Dropped rows (missing Date/Amount): {before - after}")

    if st.session_state.get("show_debug", False):
        st.text(f"Debug - After parsing count: {len(df)}")
        if not df.empty:
            st.write("Debug - After parsing (head):", df.head())

    # --- Filter out payments before origination date ---
    if st.session_state.get("show_debug", False):
        st.text(f"Debug - Origination date: {origination_date} ({type(origination_date).__name__})")
    df = df[df["Date"] >= origination_date]

    if st.session_state.get("show_debug", False):
        st.text(f"Debug - After filtering count: {len(df)}")
        if not df.empty:
            st.write("Debug - After filtering (head):", df.head())

    # --- Core schedule calculation (Actual/365 simple interest) ---
    df = df.sort_values("Date")
    schedule = []
    bal = round(float(principal), 2)
    last_date = origination_date
    accrued_carry = 0.0

    for _, row in df.iterrows():
        d = row["Date"]
        amt = float(row["Amount"])
        days = (d - last_date).days
        interest_accrued = bal * annual_rate * (days / 365.0) if days > 0 else 0.0
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

# ============================================================================
# CRITICAL FUNCTION: PDF Report Generation
# ============================================================================
# DO NOT MODIFY THIS FUNCTION WITHOUT UPDATING FEATURE_CHECKLIST.md
# This function generates the complete PDF report with all calculations
# ============================================================================

def build_pdf(df, principal, origination_date, annual_rate, term_years):
    buf = BytesIO()
    pp = PdfPages(buf)

    # Summary page
    fig = plt.figure(figsize=(8.5, 11))
    fig.clf()
    r = annual_rate / 12.0
    n = int(term_years * 12)
    ref_payment = 0.0 if r <= 0 or n <= 0 else round(principal * r / (1 - (1+r)**(-n)), 2)

    summary = f"""\
Loan Payment Report

Original Principal: ${principal:,.2f}
Origination Date: {origination_date:%B %d, %Y}
Interest Rate: {annual_rate*100:.3f}% APR (Actual/365 simple interest)
Loan Term: {term_years} years

Reference Monthly Payment (level-pay): ${ref_payment:,.2f}

Generated: {date.today():%B %d, %Y}

Results:
• Last recorded payment: {df['Payment Date'].max():%b %d, %Y}
• Principal remaining after last payment: ${df['Principal Balance After Payment'].iloc[-1]:,.2f}
• Total interest paid to date: ${df['Interest Applied'].sum():,.2f}
• Total principal repaid to date: ${df['Principal Applied'].sum():,.2f}

Assumptions:
• Payments before origination excluded
• Interest accrues daily on principal only; unpaid interest does not compound
• Payments applied to accrued interest first, then principal
"""
    import textwrap
    wrapped = "\n".join([textwrap.fill(line, width=90) for line in summary.strip().splitlines()])
    plt.axis('off')
    plt.text(0.05, 0.95, wrapped, va='top', ha='left', fontsize=10, family='monospace')
    pp.savefig(fig)
    plt.close(fig)

    # Per-payment table
    cols = ["Payment Date","Payment Amount","Days Since Last Payment",
            "Interest Accrued Since Last Payment","Interest Applied",
            "Principal Applied","Principal Balance After Payment"]
    dfp = df.copy()
    dfp["Payment Date"] = pd.to_datetime(dfp["Payment Date"]).dt.strftime("%Y-%m-%d")
    rows_per_page = 25
    for start in range(0, len(dfp), rows_per_page):
        chunk = dfp.iloc[start:start+rows_per_page][cols]
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

    # Monthly balances table - only show months with actual interest accrual
    df_sorted = df.sort_values("Payment Date")
    if not df_sorted.empty:
        last_payment_date = df_sorted["Payment Date"].max()
        # Only show months up to the last payment date, plus current month if there's interest accrual
        end_month = last_payment_date.replace(day=1)  # Start of month of last payment
        
        # Check if we need to add current month (only if there's been time since last payment)
        today = date.today()
        days_since_last_payment = (today - last_payment_date).days
        if days_since_last_payment > 0:
            # Add current month if there's been time for interest to accrue
            current_month_start = date(today.year, today.month, 1)
            if current_month_start > end_month.replace(day=1):
                end_month = current_month_start
        
        start_month = date(origination_date.year, origination_date.month, 1)
        
        # Build monthly principal balances using the schedule
        bal = float(principal)
        accrued_carry = 0.0
        last_event_date = origination_date
        payments_sorted = df_sorted[["Payment Date","Payment Amount"]].to_records(index=False)

        monthly_rows = []
        pay_idx = 0
        cur = start_month
        
        while cur <= end_month:
            nm = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
            eom = nm - timedelta(days=1)
            
            # Process all payments in this month
            month_has_activity = False
            while pay_idx < len(payments_sorted) and payments_sorted[pay_idx][0] <= eom:
                d = payments_sorted[pay_idx][0]
                amt = float(payments_sorted[pay_idx][1])
                days = (d - last_event_date).days
                interest_accrued = bal * annual_rate * (days / 365.0) if days > 0 else 0.0
                interest_due = interest_accrued + accrued_carry
                if amt >= interest_due:
                    principal_applied = round(amt - interest_due, 2)
                    bal = round(bal - principal_applied, 2)
                    accrued_carry = 0.0
                else:
                    accrued_carry = round(interest_due - amt, 2)
                last_event_date = d
                pay_idx += 1
                month_has_activity = True
            
            # Only add month if there was activity (payments) or if it's the current month with interest accrual
            if month_has_activity or (cur == end_month and days_since_last_payment > 0):
                monthly_rows.append({"Month End": eom, "Principal Balance": bal})
            
            cur = nm
    else:
        # No payments - create empty monthly table
        monthly_rows = []

    dfm = pd.DataFrame(monthly_rows)
    dfm["Month End"] = pd.to_datetime(dfm["Month End"]).dt.strftime("%Y-%m-%d")

    rows_per_page = 40
    for start in range(0, len(dfm), rows_per_page):
        chunk = dfm.iloc[start:start+rows_per_page]
        fig = plt.figure(figsize=(8.5, 11))
        ax = fig.add_subplot(111)
        ax.axis('off')
        tbl = ax.table(cellText=chunk.values, colLabels=chunk.columns, loc='center')
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8)
        tbl.scale(1, 1.2)
        ax.set_title("Monthly Principal Balance (End of Month)", fontsize=12, pad=20)
        pp.savefig(fig, bbox_inches='tight')
        plt.close(fig)

    pp.close()
    buf.seek(0)
    return buf.getvalue()

if st.button("Calculate & Show Tables"):
    df = compute_schedule(
        current_loan_data["principal"], 
        current_loan_data["origination_date"], 
        current_loan_data["annual_rate"] / 100,  # Convert back to decimal
        current_loan_data["payments_df"]
    )
    if df.empty:
        st.warning("No payments on/after origination date.")
    else:
        st.success("Calculated.")
        # Configure column display with specific pixel widths for optimal layout
        st.dataframe(
            df,
            width='stretch',
            column_config={
                "Payment Date": st.column_config.DateColumn(
                    "Payment Date",
                    format="MM/DD/YYYY",
                    width=80,
                    help="Date when payment was made"
                ),
                "Days Since Last Payment": st.column_config.NumberColumn(
                    "Days Since Last Payment",
                    width=60,
                    help="Number of days since the previous payment"
                ),
                "Payment Amount": st.column_config.NumberColumn(
                    "Payment Amount",
                    format="$%.2f",
                    width=100,
                    help="Total payment amount received"
                ),
                "Interest Accrued Since Last Payment": st.column_config.NumberColumn(
                    "Interest Accrued Since Last Payment",
                    format="$%.2f",
                    width=120,
                    help="Interest that accrued between this payment and the previous one"
                ),
                "Interest Applied": st.column_config.NumberColumn(
                    "Interest Applied",
                    format="$%.2f",
                    width=100,
                    help="Portion of payment applied to interest"
                ),
                "Principal Applied": st.column_config.NumberColumn(
                    "Principal Applied",
                    format="$%.2f",
                    width=100,
                    help="Portion of payment applied to principal reduction"
                ),
                "Principal Balance After Payment": st.column_config.NumberColumn(
                    "Principal Balance After Payment",
                    format="$%.2f",
                    width=120,
                    help="Remaining principal balance after this payment"
                )
            },
            hide_index=True
        )
        
        # Show current interest accrual since last payment
        if not df.empty:
            last_payment_date = df["Payment Date"].max()
            last_principal_balance = df["Principal Balance After Payment"].iloc[-1]
            today = date.today()
            days_since_last_payment = (today - last_payment_date).days
            
            if days_since_last_payment > 0:
                current_interest_rate = current_loan_data["annual_rate"] / 100
                interest_accrued_since_last = last_principal_balance * current_interest_rate * (days_since_last_payment / 365.0)
                
                st.subheader("Current Status")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Days Since Last Payment", days_since_last_payment)
                with col2:
                    st.metric("Current Principal Balance", f"${last_principal_balance:,.2f}")
                with col3:
                    st.metric("Interest Accrued Since Last Payment", f"${interest_accrued_since_last:,.2f}")
                
                st.info(f"**Note**: Interest continues to accrue daily at {current_interest_rate*100:.3f}% APR on the current principal balance of ${last_principal_balance:,.2f}")

if st.button("Generate PDF Report"):
    df = compute_schedule(
        current_loan_data["principal"], 
        current_loan_data["origination_date"], 
        current_loan_data["annual_rate"] / 100,  # Convert back to decimal
        current_loan_data["payments_df"]
    )
    if df.empty:
        st.warning("No payments on/after origination date.")
    else:
        pdf_bytes = build_pdf(
            df, 
            current_loan_data["principal"], 
            current_loan_data["origination_date"], 
            current_loan_data["annual_rate"] / 100,  # Convert back to decimal
            current_loan_data["term_years"]
        )
        fname = f"loan_report_{current_loan}_{date.today().isoformat()}.pdf"
        st.download_button("Download PDF", data=pdf_bytes, file_name=fname, mime="application/pdf")

# Data Persistence Section
with st.expander("💾 Data Persistence", expanded=False):
    st.info("""
    **Automatic Saving**: Your loan data is automatically saved to `loan_data.json` whenever you:
    - Upload a CSV file
    - Modify loan terms in the sidebar
    - Add, rename, or delete loans
    - Edit payments in the table below
    """)
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 Manual Save", help="Force save all current data"):
            save_data()
            st.success("✅ Data saved successfully!")
    
    with col2:
        if st.button("🔄 Reload Data", help="Reload data from saved file"):
            saved_data = load_data()
            if saved_data:
                st.session_state.loans = saved_data["loans"]
                st.session_state.current_loan = saved_data["current_loan"]
                st.success("✅ Data reloaded successfully!")
                st.rerun()
            else:
                st.warning("No saved data found.")

st.info("Run locally: 1) pip install streamlit matplotlib pandas  2) streamlit run loan_app.py")

# ============================================================================
# CRITICAL SECTION: Feature Validation
# ============================================================================
# Validate critical features after all functions are defined
if not validate_critical_features():
    st.stop()