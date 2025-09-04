# shylock_ledger.py
from __future__ import annotations
from datetime import date as _date, timedelta as _timedelta, datetime as _dt
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import re
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

# ---------------- small helpers ----------------
def _dec(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _fmt_money(x) -> str:
    try:
        return f"${float(x):,.2f}"
    except Exception:
        return "$0.00"

def _format_us_date(d):
    try:
        return _dt.strftime(pd.to_datetime(d).to_pydatetime(), "%m/%d/%Y")
    except Exception:
        return ""

def parse_us_date(s: str):
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

def _last_day_of_month(y: int, m: int) -> int:
    if m == 12:
        return (_date(y + 1, 1, 1) - _timedelta(days=1)).day
    return (_date(y, m + 1, 1) - _timedelta(days=1)).day

def add_months(d: _date, months: int) -> _date:
    y = d.year + (d.month - 1 + months) // 12
    m = ((d.month - 1 + months) % 12) + 1
    day = min(d.day, _last_day_of_month(y, m))
    return _date(y, m, day)

# ---------------- core: one-row-per-due-date engine ----------------
def compute_ledger(
    principal: float,
    origination_date: _date,
    annual_rate_decimal: float,
    payments_df: pd.DataFrame,
    *,
    grace_days: int = 4,
    late_fee_type: str = "fixed",         # "fixed" or "percent"
    late_fee_amount: float = 0.0,         # if percent, % of cycle interest due
) -> pd.DataFrame:
    """
    Policy implemented (per user spec):
    - One row per due date (monthly cadence based on origination day).
    - "Amount due" for a cycle = simple interest on beginning principal for the
      days from previous due to current due (ACT/365). Prepayments do not
      reduce this cycle's interest; they are carried to future cycles.
    - If the cycle's interest is not fully paid by due date + grace, a late fee
      is assessed and CAPITALIZED (added to principal at grace).
    - Principal reduction occurs ONLY when the payment that finally satisfies a
      cycle occurs on/after the due date AND exceeds the interest due for the
      cycle; the on-date excess is applied to principal. Any pre-due excess is
      reserved for future cycles (no principal reduction before due date).
    """
    # Normalize payments
    if payments_df is None or payments_df.empty:
        payments = []
    else:
        tmp = payments_df.copy()
        # expected columns: payment_date, amount
        tmp["payment_date"] = pd.to_datetime(tmp["payment_date"], errors="coerce").dt.date
        tmp["amount"] = pd.to_numeric(tmp["amount"], errors="coerce")
        tmp = tmp.dropna().sort_values("payment_date")
        # collapse same-day multiple lines to one pool (keeps logic simple)
        payments = (
            tmp.groupby("payment_date", as_index=False)["amount"]
               .sum()
               .to_dict("records")
        )

    P = _dec(principal)
    r = Decimal(str(annual_rate_decimal))

    rows = []
    i = 0
    pay_idx = 0
    carry = _dec(0)     # unapplied amount carried into future cycles

    # compute through the last due date that is needed to allocate all payments
    last_pay_dt = payments[-1]["payment_date"] if payments else origination_date
    # produce due dates until we've passed the last payment date by one cycle
    max_due_dt = add_months(origination_date, 1)
    while max_due_dt <= (add_months(last_pay_dt, 1) if payments else add_months(origination_date, 1)):
        max_due_dt = add_months(max_due_dt, 1)

    prev_due = origination_date
    due = add_months(origination_date, 1)

    while due <= max_due_dt:
        days_in_cycle = (due - prev_due).days
        cycle_interest = (P * r * Decimal(days_in_cycle) / Decimal(365)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        grace_dt = due + _timedelta(days=int(grace_days or 0))

        # --- collect payments up to due date (prepayments) ---
        # add all payments up to and including the due date into carry
        while pay_idx < len(payments) and payments[pay_idx]["payment_date"] <= due:
            carry += _dec(payments[pay_idx]["amount"])
            pay_idx += 1

        paid_before_or_on_due = carry
        payment_date_to_satisfy = None

        if paid_before_or_on_due >= cycle_interest:
            # Satisfied on/before due date: use the last payment ON/BY due (if any)
            # Backtrack to find the date that pushed it over, else mark as due date.
            # We compute by scanning backwards over the payments <= due.
            overshoot_needed = cycle_interest
            t_idx = pay_idx - 1
            rem = carry
            while t_idx >= 0 and payments[t_idx]["payment_date"] <= due and overshoot_needed > 0:
                amt = _dec(payments[t_idx]["amount"])
                if rem - amt < overshoot_needed:
                    payment_date_to_satisfy = payments[t_idx]["payment_date"]
                rem -= amt
                overshoot_needed -= min(overshoot_needed, amt)
                t_idx -= 1
            if payment_date_to_satisfy is None:
                payment_date_to_satisfy = due  # satisfied via earlier carry
            # consume only what is needed; leave remainder for next cycle(s)
            carry = (carry - cycle_interest).quantize(Decimal("0.01"))
            late_fee = _dec(0)
            days_late = 0
            principal_applied = _dec(0)  # never reduce principal before due
            posted_amount = cycle_interest  # the portion used for this cycle
        else:
            # Not satisfied by due date -> keep consuming payments AFTER due until covered
            amt_used = carry
            last_used_idx = None
            while amt_used < cycle_interest and pay_idx < len(payments):
                amt_used += _dec(payments[pay_idx]["amount"])
                last_used_idx = pay_idx
                pay_idx += 1

            if amt_used >= cycle_interest and last_used_idx is not None:
                payment_date_to_satisfy = payments[last_used_idx]["payment_date"]
                days_late = max(0, (payment_date_to_satisfy - due).days)
                # Was it satisfied after grace?
                late_fee = _dec(0)
                if payment_date_to_satisfy > grace_dt:
                    if (late_fee_type or "fixed") == "percent":
                        late_fee = (cycle_interest * Decimal(late_fee_amount) / Decimal(100)).quantize(Decimal("0.01"))
                    else:
                        late_fee = _dec(late_fee_amount)
                    P = (P + late_fee).quantize(Decimal("0.01"))  # CAPITALIZE AT GRACE

                # determine extra from the last payment used ON that date
                # (we only allow principal reduction if satisfaction occurs on/after due)
                extra_on_that_date = (amt_used - cycle_interest)
                carry = _dec(0)  # carry was fully consumed to reach interest; any extra is from last tx
                principal_applied = _dec(0)
                if extra_on_that_date > 0 and payment_date_to_satisfy >= due:
                    principal_applied = extra_on_that_date
                else:
                    # extra that happened BEFORE due stays as carry; but we are in the "after due" branch,
                    # so only possible extra is on the satisfaction date; keep none for carry here.
                    pass
                posted_amount = (cycle_interest + principal_applied).quantize(Decimal("0.01"))
            else:
                # No more payments; record through due date with deficiency; assess late fee
                payment_date_to_satisfy = None
                days_late = max(0, (_date.today() - due).days)
                if (late_fee_type or "fixed") == "percent":
                    late_fee = (cycle_interest * Decimal(late_fee_amount) / Decimal(100)).quantize(Decimal("0.01"))
                else:
                    late_fee = _dec(late_fee_amount)
                P = (P + late_fee).quantize(Decimal("0.01"))
                principal_applied = _dec(0)
                posted_amount = carry  # whatever was in carry (partial), for completeness
                carry = _dec(0)

        # principal for next cycle
        P = (P - principal_applied).quantize(Decimal("0.01"))

        rows.append({
            "Due Date": due,
            "Payment Date (Posted)": payment_date_to_satisfy,
            "Days Late": int(days_late),
            "Payment Amount (Posted)": float(posted_amount),
            "Accrued Interest (Cycle)": float(cycle_interest),
            "Late Fee (Assessed)": float(late_fee),
            "Allocated → Principal": float(principal_applied),
            "Principal Balance (End)": float(P),
        })

        prev_due = due
        due = add_months(due, 1)

    df = pd.DataFrame(rows)
    # Pretty types
    if not df.empty:
        df["Due Date"] = pd.to_datetime(df["Due Date"]).dt.date
        df["Payment Date (Posted)"] = pd.to_datetime(df["Payment Date (Posted)"]).dt.date
        for c in ["Payment Amount (Posted)","Accrued Interest (Cycle)","Late Fee (Assessed)",
                  "Allocated → Principal","Principal Balance (End)"]:
            df[c] = pd.to_numeric(df[c]).round(2)
    return df

# ---------------- custom header + grid ----------------
def render_wrapped_header(labels_in_order, widths_px, angle_labels: bool = True):
    cols_css = " ".join(f"{max(80, int(w))}px" for w in widths_px)
    st.markdown("""
    <style>
      div[data-testid="stDataEditor"] .rdg-header-row { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

    rotate_css = (
        "transform: rotate(-26deg); transform-origin: left bottom; "
        "position: absolute; left: 6px; bottom: 6px; "
        "display: inline-block; white-space: nowrap;"
    ) if angle_labels else "position: static; white-space: normal;"

    def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    cells = "".join(
        f"<div class='hdr-cell'><span class='hdr-label' style='{rotate_css}'>{esc(lbl)}</span></div>"
        for lbl in labels_in_order
    )
    st.markdown(
        f"""
<style>
.ledger-header-grid {{
  display: grid; grid-template-columns: {cols_css}; gap: 6px; width: 100%;
  align-items: end; margin: 6px 0 8px 0;
}}
.ledger-header-grid .hdr-cell {{
  position: relative; height: 86px; padding: 8px 8px;
  border: 1px solid rgba(0,0,0,0.08); border-radius: 6px; background: #fafafa;
  overflow: visible;
}}
.ledger-header-grid .hdr-label {{
  font-family: system-ui, -apple-system, Segoe UI, Roboto, 'Helvetica Neue', Arial, 'Noto Sans', 'Liberation Sans', sans-serif;
  font-size: 12px; line-height: 1.2; font-weight: 700; color: rgba(0,0,0,0.85);
}}
</style>
<div class="ledger-header-grid">{cells}</div>
""",
        unsafe_allow_html=True,
    )

def make_display(ledger: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    existing = [c for c in order if c in ledger.columns]
    return ledger[existing].copy()

def render_ledger(df_to_show: pd.DataFrame, widths: dict[str, int], short_labels: dict[str, str], *, angle_labels=True):
    ordered_cols = list(df_to_show.columns)
    header_labels = ordered_cols[:]
    header_widths = [widths.get(c, 120) for c in ordered_cols]
    render_wrapped_header(header_labels, header_widths, angle_labels=angle_labels)

    renamed = {c: short_labels.get(c, c) for c in ordered_cols}
    df_grid = df_to_show.rename(columns=renamed)

    cfg = {}
    for c in ordered_cols:
        short = renamed[c]; w = widths.get(c, 120)
        if "Date" in c:
            cfg[short] = st.column_config.DateColumn(format="MM/DD/YYYY", width=w)
        elif "Days Late" in c:
            cfg[short] = st.column_config.NumberColumn(format="%d", width=w)
        else:
            cfg[short] = st.column_config.NumberColumn(format="$%.2f", width=w)

    st.data_editor(
        df_grid, use_container_width=True, hide_index=True, disabled=True,
        height=460, column_config=cfg, key="ledger_grid_readonly"
    )

# ---------------- PDF ----------------
def build_pdf_from_ledger(ledger: pd.DataFrame, loan_meta: dict) -> bytes:
    buf = BytesIO(); pp = PdfPages(buf)

    fig = plt.figure(figsize=(8.5, 11)); fig.clf(); plt.axis('off')
    loan_label = loan_meta.get('loan_name') or loan_meta.get('name') or 'Loan'
    title = "Loan Statement"; subtitle = f"{loan_label} — Generated { _date.today():%b %d, %Y }"
    lines = [title, subtitle, "",
             f"Lender: {loan_meta.get('lender_name','')}",
             f"Borrower: {loan_meta.get('borrower_name','')}",
             f"Origination: {_format_us_date(loan_meta.get('origination_date')) or '—'}",
             f"APR: {float(loan_meta.get('annual_rate', 0.0)):.3f}% (ACT/365 simple interest)", ""]
    if not ledger.empty:
        begin_prin = float(loan_meta.get("principal", 0.0))
        end_prin = float(ledger.iloc[-1]["Principal Balance (End)"])
        tot_pay = float(ledger["Payment Amount (Posted)"].sum())
        tot_late = float(ledger.get("Late Fee (Assessed)", pd.Series([0])).sum())
        tot_prin = float(ledger.get("Allocated → Principal", pd.Series([0])).sum())
        tot_int = float(ledger.get("Accrued Interest (Cycle)", pd.Series([0])).sum())
    else:
        begin_prin = float(loan_meta.get("principal", 0.0)); end_prin = begin_prin
        tot_pay = tot_late = tot_prin = tot_int = 0.0

    summary = [
        f"Beginning Principal Balance: {_fmt_money(begin_prin)}",
        f"Payments Posted (Total): {_fmt_money(tot_pay)}",
        f"Accrued Interest (All Cycles): {_fmt_money(tot_int)}",
        f"Late Fees Assessed (Total): {_fmt_money(tot_late)}",
        f"Allocated to Principal (Total): {_fmt_money(tot_prin)}",
        f"Ending Principal Balance: {_fmt_money(end_prin)}", "",
        "Allocation: Early payments satisfy the next due interest; principal reduces only if the cycle is satisfied on/after the due date and the same-day payment exceeds the interest due.",
        "Late fee is capitalized at grace when the cycle is not satisfied by due+grace.",
    ]
    y = 0.95
    for s in lines:
        plt.text(0.05, y, s, ha='left', va='top', fontsize=11,
                 family='sans-serif', weight='bold' if s == title else 'normal'); y -= 0.035
    y -= 0.01
    for s in summary:
        plt.text(0.05, y, s, ha='left', va='top', fontsize=10, family='monospace'); y -= 0.028
    pp.savefig(fig, bbox_inches='tight'); plt.close(fig)

    if not ledger.empty:
        dfp = ledger.copy()
        dfp["Due Date"] = pd.to_datetime(dfp["Due Date"]).dt.strftime("%m/%d/%Y")
        dfp["Payment Date (Posted)"] = pd.to_datetime(dfp["Payment Date (Posted)"]).dt.strftime("%m/%d/%Y")
        currency_cols = ["Payment Amount (Posted)","Accrued Interest (Cycle)","Late Fee (Assessed)",
                         "Allocated → Principal","Principal Balance (End)"]
        for c in currency_cols:
            if c in dfp.columns: dfp[c] = dfp[c].apply(_fmt_money)
        cols = ["Due Date","Payment Date (Posted)","Days Late","Payment Amount (Posted)",
                "Late Fee (Assessed)","Accrued Interest (Cycle)",
                "Allocated → Principal","Principal Balance (End)"]
        rows_per_page = 24
        for start in range(0, len(dfp), rows_per_page):
            chunk = dfp.iloc[start:start + rows_per_page][cols]
            fig = plt.figure(figsize=(8.5, 11)); ax = fig.add_subplot(111); ax.axis('off')
            ax.set_title("Payment & Accrual Activity", fontsize=12, pad=16)
            tbl = ax.table(cellText=chunk.values, colLabels=chunk.columns, loc='center')
            tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1, 1.2)
            pp.savefig(fig, bbox_inches='tight'); plt.close(fig)
    pp.close(); buf.seek(0)
    return buf.getvalue()