# Shylock — Private Loan Servicing (MVP)

**Stack:** Streamlit (web), Supabase (Postgres + Auth), Python core logic  
**Focus:** Manual payment posting, accurate allocation (Penalty Interest → Late Fees → Loan Interest → Principal), lender-grade statements

---

## 1) Problem & Users

- **Problem:** Individuals who lend privately (family/friends/club deals) lack simple tools to post **irregular payments** and allocate them correctly, especially with **late fees** and **penalty interest**. Generic amortization calculators assume fixed schedules and don’t create lender-grade statements.
- **Primary Users:** Individual private lenders (1–50 active loans).  
- **Secondary Users:** Small investor groups, family offices, or trustees.

---

## 2) Scope: Goals vs Non-Goals

### MVP Goals
1. **Auth & Isolation**
   - Email/password + magic link (Google/Apple later via Supabase).
   - Row-Level Security: each lender sees only their own loans/data.

2. **Loan Setup**
   - principal, APR (annual rate), origination date, term (years).
   - day-count basis: **ACT/365** (MVP); 30/360 later.
   - **Late fee rules:** fixed ($) or percent (% of a reference payment), grace period days.
   - **Penalty interest APR:** optional override; defaults to loan APR.

3. **Payments & Ledger**
   - Post payments by **date** and **amount** (CSV upload + manual add).
   - Compute **accrued loan interest** (ACT/365 simple).
   - Assess **late fee** if payment date > due date + grace.
   - Accrue **penalty interest** daily on **unpaid late fees**.
   - Allocation order: **Penalty Interest → Late Fees → Loan Interest → Principal**.
   - Maintain **running balances** (principal, outstanding late fees, outstanding penalty interest).

4. **Borrower Link (Read-Only)**
   - Share a tokenized URL to let a borrower view their loan’s ledger.

5. **Exports**
   - **PDF Statement** with summary + ledger.
   - **CSV** export (columns mirror the ledger).

### Non-Goals (MVP)
- Native mobile apps (see Mobile Roadmap).
- Borrower payment portal/processing (ACH/Stripe).  
- Complex fee engines, escrow/impounds, multi-currency.  
- Jurisdiction-specific legal compliance engine (see Disclosures).

---

## 3) Core User Flows & Acceptance Criteria

1) **Create Loan**
- Inputs: name, principal, APR, origination_date, term_years, late_fee_type (fixed/percent), late_fee_amount, late_fee_days, penalty_interest_rate (optional).  
- **AC:** Loan saved; appears in lender dashboard; borrower token can be generated.

2) **Upload/Post Payments**
- CSV with `Date, Amount` or `Payment Date, Amount`; manual add form.  
- **AC:** Payments persist; ledger recomputes; negative amortization allowed.

3) **Ledger**
- Shows per-event: Due Date, Payment Date, Payment Amount, Accrued Loan Interest, **Penalty Interest Accrued**, **Late Fee (Assessed)**, Allocations (→Penalty Int, →Late Fees, →Loan Int, →Principal), and end balances (Principal, Late Fees Outstanding, Penalty Interest Outstanding).  
- **AC:** Allocation order strictly enforced; outstanding buckets update correctly.

4) **PDF Statement & CSV**
- **PDF** has: header (lender/borrower/loan), account summary (begin/end principal, totals allocated to each bucket, outstanding late/penalty interest), activity table (key columns).  
- **CSV** mirrors ledger columns 1:1.  
- **AC:** Values in exports match on-screen ledger.

5) **Borrower Read-Only View**
- `?role=borrower&token=...` shows the same ledger without edit controls.  
- **AC:** No data changes permitted; token can be rotated.

---

## 4) Domain Rules (MVP)

- **Interest basis:** ACT/365 simple on principal only.  
- **Unpaid loan interest** does **not** itself accrue interest (no compounding of loan interest).  
- **Late fees**: assessed when `payment_date > (due_date + grace_days)`.  
  - If **percent**, percent is applied to a **reference scheduled payment** (MVP heuristic: interest-only proxy; can be replaced by actual scheduled amount in v2).  
- **Penalty interest**: accrues **daily** on **outstanding late-fee principal** at **Penalty APR** or **loan APR** if none set. Penalty interest does not compound; it’s a separate bucket.  
- **Allocation order:** Penalty Interest → Late Fees → Loan Interest → Principal.  
- **Rounding:** store amounts as decimal; display with 2 decimals; round at persistence/render only.

---

## 5) Data Model (Supabase / Postgres)

> Works with your existing lightweight schema while enabling late fees and penalty APR.

```sql
-- profiles (PK = auth.users.id)
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text unique,
  company_name text,
  created_at timestamptz default now()
);

-- loans
create table if not exists public.loans (
  id uuid primary key default gen_random_uuid(),
  lender_id uuid not null references auth.users(id) on delete cascade,
  lender_name text,
  name text,
  principal numeric(14,2) not null,
  annual_rate numeric(9,6) not null,         -- percent (e.g., 5.000000)
  origination_date date not null,
  term_years int,
  borrower_name text,
  borrower_token text,                        -- for read-only token link
  late_fee_type text default 'fixed',         -- 'fixed' | 'percent'
  late_fee_amount numeric(14,2) default 0,    -- $ or % number
  late_fee_days int default 0,                -- grace period
  penalty_interest_rate numeric(9,6),         -- percent; null => use annual_rate
  created_at timestamptz default now()
);

-- payments (actuals)
create table if not exists public.payments (
  id uuid primary key default gen_random_uuid(),
  loan_id uuid not null references public.loans(id) on delete cascade,
  payment_date date not null,
  amount numeric(14,2) not null check (amount > 0),
  created_at timestamptz default now()
);

-- Optional: explicit borrower linking for signed-in borrowers
create table if not exists public.loan_borrowers (
  loan_id uuid not null references public.loans(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  primary key (loan_id, user_id)
);
```

### Row-Level Security (sketch)

```sql
alter table public.profiles enable row level security;
alter table public.loans enable row level security;
alter table public.payments enable row level security;
alter table public.loan_borrowers enable row level security;

create policy "profiles_self" on public.profiles
  for select using (id = auth.uid());
create policy "profiles_self_write" on public.profiles
  for insert with check (id = auth.uid());

create policy "loans_owner" on public.loans
  for select using (lender_id = auth.uid());
create policy "loans_owner_write" on public.loans
  for insert with check (lender_id = auth.uid());
create policy "loans_owner_update" on public.loans
  for update using (lender_id = auth.uid());

create policy "payments_via_loan" on public.payments
  for select using (exists (select 1 from public.loans l where l.id = loan_id and l.lender_id = auth.uid()));
create policy "payments_via_loan_write" on public.payments
  for insert with check (exists (select 1 from public.loans l where l.id = loan_id and l.lender_id = auth.uid()));
create policy "payments_via_loan_update" on public.payments
  for update using (exists (select 1 from public.loans l where l.id = loan_id and l.lender_id = auth.uid()));
```

---

## 6) Interest & Penalty Algorithms (MVP)

- **Loan interest (ACT/365 simple):**  
  `accrued_loan_interest = principal_balance * APR * days_elapsed / 365`  
- **Penalty interest:**  
  `accrued_penalty_interest = late_fees_outstanding * (penalty_APR or APR) * days_elapsed / 365`  
- **Allocation (on payment):**  
  1) Pay **accrued penalty interest** (reduce outstanding penalty interest).  
  2) Pay **late fees outstanding** (reduce late-fee principal).  
  3) Pay **loan interest due** (accrued + prior unpaid carry).  
  4) Remainder to **principal** (reduce principal balance).  
- **Carry:** unpaid **loan interest** remains as **non-compounding carry**.

---

## 7) Product Surfaces

### Web App (Streamlit)
- **Lender dashboard:** list loans, create/edit terms (incl. late fee rules), upload/add payments, view ledger, export PDF/CSV.  
- **Borrower view:** tokenized read-only ledger.

### Exports
- **PDF Statement:**  
  - Header: lender/borrower/loan, origination date, APR, late fee/penalty APR settings.  
  - Summary box: beginning principal, payments total, allocations totals (penalty interest, late fees, loan interest, principal), ending principal, outstanding late fees & penalty interest.  
  - Activity table: Payment Date, Due Date, Payment Amount, Penalty Interest Accrued, Late Fee (Assessed), Allocations, End Balances.  
  - Disclaimer: informational only; lender responsible for legal compliance.  
- **CSV:** Mirrors the ledger columns for external analysis.

---

## 8) Repo Structure & Guardrails

```
shylock/
  apps/
    mvp/                  # minimal Streamlit app (frozen, stable)
    pro/                  # experimental Streamlit app (new features)
  packages/
    ledger_core/          # pure Python domain logic (interest, penalties)
      ledger/
        __init__.py
        interest.py
        allocation.py
        models.py
      tests/
  infra/
    supabase/
      001_init.sql
      002_rls.sql
  docs/
    PRD.md
  .cursorrules
  pyproject.toml
  README.md
```

**Cursor Guardrails (`.cursorrules`):**
```
deny-edit: ["apps/mvp/**", "packages/ledger_core/**"]
allow-edit: ["apps/pro/**", "docs/**", "infra/**"]
```

- Promote features from `pro` → `mvp` only after tests pass.

---

## 9) Testing

- **Unit tests (packages/ledger_core/tests):**  
  - Interest accrual across gaps (ACT/365), month boundaries, leap year day counts.  
  - Late fee assessment relative to due date + grace.  
  - Penalty interest accrual on unpaid late fees.  
  - Allocation order with edge cases (tiny payments, under/over payments).  
- **Snapshot test:** Known loan + fixed payment set → assert balances on specific dates.  
- **Smoke test:** Create loan → add payments → export CSV/PDF; check totals non-negative and consistent.

---

## 10) Analytics & Audit

- **Audit log** (optional MVP): JSON of key actions: `CREATE_LOAN`, `POST_PAYMENT`, `GENERATE_STATEMENT`.  
- **Minimal telemetry:** Count of statements generated per loan.

---

## 11) Disclosures & Legal Considerations (Flagged)

- The app **does not** generate jurisdiction-specific disclosures.  
- **Consumer-purpose loans** may trigger U.S. **Truth in Lending Act (TILA)** and other regulations; **business-purpose loans** may be exempt.  
- MVP includes a **disclaimer** on statements and setup screens.  
- Future: add a “Compliance” research track (jurisdiction, thresholds, APR definitions, fee limits, notices).

---

## 12) Mobile Roadmap

- **Phase 1 (MVP):** Responsive Streamlit web app (works on mobile browsers).  
- **Phase 2:** Wrap as a WebView container (Capacitor/Expo) for testflight/internal distribution.  
- **Phase 3:** Native/hybrid app (React Native/Flutter) that reuses **Supabase** backend and **ledger_core** package.

---

## 13) Risks & Mitigations

- **Cursor overwriting stable code** → repo split (mvp vs pro) + `.cursorrules` + unit tests.  
- **Auth redirect quirks** → keep email/password + magic link; add Google/Apple after staging.  
- **Math disputes** → store and show accrual windows, allocation order, and running balances; prefer deterministic rounding.

---

## 14) Rollout Plan

1. Stand up Supabase project; run `infra/supabase/*.sql`.  
2. Deploy Streamlit app; configure `secrets.toml` with `SUPABASE_URL` and `SUPABASE_ANON_KEY`.  
3. Seed one demo loan + payments; validate ledger & PDF with known scenario.  
4. Invite 3–10 real testers (lenders); collect feedback on late fee behavior, statement clarity.  
5. Iterate in `apps/pro`; promote stabilized features to `apps/mvp`.

--- 

**Definition of Done (MVP v1.0):**  
- Lender can create a loan, post payments (CSV + manual), see accurate ledger with late fees & penalty interest, and export a clear PDF + CSV.  
- Borrower can view a read-only ledger via token.  
- RLS enforced; basic tests pass; repo guardrails in place.
