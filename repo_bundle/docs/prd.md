# Shylock Loan Servicing App — Product Requirements Document

## Vision
Provide private lenders (friends, family, informal lenders) with a professional yet lightweight tool to manage loans, track irregular payments, and generate compliant statements. The app should bridge the gap between simple amortization calculators and expensive enterprise loan servicing systems.

## Goals
- MVP: deliver a functional web app that supports loan setup, irregular payment posting, automatic allocation (interest, late fees, principal), and clean exports (CSV, PDF).
- Scalability: codebase structured so features can expand without breaking MVP (e.g., mobile wrapper, reminders, multi-loan portfolios).

## Non-Goals
- Not a mobile-native iOS/Android app (initially web-based via Streamlit).
- Not a full banking/compliance system; disclosures should be flagged for lender awareness but not enforced.

---

## Target Users
- **Lenders:** Individuals lending money to friends/family/peers, wanting to track payments and balances clearly.
- **Borrowers:** Read-only view of loan statements and balances (via secure tokenized link or login).

---

## Key Features (MVP)
1. **Authentication**
   - Supabase email/password, magic links, Google/Apple OAuth (optional later).
   - Roles: Lender vs Borrower.
   - Borrower access via secure tokenized URL.

2. **Loan Setup**
   - Fields: `loan_name`, `principal`, `annual_rate`, `origination_date`, `term_years`, `borrower_name`, `borrower_email`, `borrower_token`.
   - Late payment settings: `late_fee_type` (fixed $ or %), `late_fee_amount`, `late_fee_days`, `penalty_interest_rate`.

3. **Payments**
   - Manual add (date + amount).
   - CSV upload (columns: Date, Amount).
   - Stored in `payments(loan_id, payment_date, amount)`.

4. **Ledger & Calculations**
   - Daily accrual ACT/365 simple interest.
   - Payment allocation order: Penalty Interest → Late Fees → Loan Interest → Principal.
   - Late fee assessment after grace period (`late_fee_days`).
   - Penalty interest accrues on unpaid late fees.
   - Carry forward unpaid loan interest.

5. **Borrower View**
   - Token-based URL, read-only access.
   - View loan terms, payment history, and current balance.

6. **Lender View**
   - Manage multiple loans.
   - Add/edit/delete loans.
   - Add/edit/delete payments.
   - View ledger table and current metrics.
   - Export: CSV ledger, PDF statement (with branding/logo).

7. **Logo Branding**
   - Display `ShylockLogo.png` at top of every page via responsive header.

---

## Data Model

### loans
- id (uuid, pk)
- lender_id (uuid, fk to auth.users)
- lender_name (text)
- loan_name (text)
- principal (numeric)
- annual_rate (numeric)
- term_years (int)
- origination_date (date)
- borrower_name (text)
- borrower_email (text)
- borrower_token (varchar)
- late_fee_type (text)
- late_fee_amount (numeric)
- late_fee_days (int)
- penalty_interest_rate (numeric)
- created_at (timestamptz default now())

### payments
- id (uuid, pk)
- loan_id (uuid, fk to loans.id)
- payment_date (date)
- amount (numeric check > 0)
- created_at (timestamptz default now())

### profiles
- id (uuid, pk, same as auth.users.id)
- email (text)
- company_name (text)
- role (text)
- name (text)

---

## Exports
- **CSV:** full ledger with accruals, allocations, balances.
- **PDF:** branded statement, summary page + detailed table.

---

## Future Enhancements (post-MVP)
- Notifications/reminders (email/SMS) for due/late payments.
- Scenario modeling (extra payments, balloon, interest-only periods).
- Multi-currency support.
- iOS/Android wrapper via Streamlit Cloud or React Native.
- Borrower ability to upload supporting docs.

---

## Compliance Considerations
- U.S. private loans generally exempt from Truth in Lending Act if not “regularly extending credit,” but disclosures may be recommended.
- App should show disclaimer in PDF/borrower view: “Informational only. Lender is responsible for compliance with applicable laws.”

---

## Competitive Analysis
- Most iOS apps are amortization calculators only; they assume fixed schedules and cannot track irregular/manual payments.
- Banktivity (general finance app) supports loans but not lender-facing servicing.
- Opportunity: specialized private-lender tool with accurate allocation and professional statements.

---

## Success Criteria
- Lender can set up loan in <5 minutes.
- Payment posting (manual or CSV) updates ledger instantly.
- Exports (CSV, PDF) are accurate and professional.
- Borrower can view their statement securely with no confusion.
