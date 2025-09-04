# Shylock Online — Feature Matrix

## Tiers at a glance

| Area | **Free (MVP)** | **Pro (Subscription)** | **Later / Consider** |
|---|---|---|---|
| Loans | Track **1** loan | **Unlimited** loans | Teams / shared access |
| Payments | CSV import + manual add | Bulk import tools, duplicate detection | Bank sync (Plaid) |
| Interest | ACT/365 simple interest | Additional day-counts (30/360, ACT/ACT) | Compounding options |
| Late fees | Fixed/percent fee, grace days, fee capitalization | Custom rules per-loan; holidays calendar | State-specific rulesets |
| Ledger | One row per due date; mobile-friendly grid; CSV export | Branded PDF statements; custom column layouts | Statement scheduling |
| Borrower portal | Read-only link per loan | Branded portal, email statements | Borrower login + reminders |
| Documents | — | **Promissory note generator** (PDF); storage in Supabase | e-sign + notarization integrations |
| Branding | Shylock Online header | Custom logo/wordmark, colors | White-label |
| Support | Community email | Priority email | Live support |
| Pricing | Free | $X / month (founder pricing) | Usage-based add-ons |

---

## MVP success criteria

- User can create 1 loan, upload CSV of payments, add a payment manually.
- Ledger shows one row per due date; late fees calculated with grace; PDF optional.
- Borrower read-only view works via secure token link.
- CSV export available; PDF export optional/guarded by “Pro” flag.

---

## Upgrade teaser (shown inside the app)

- “Upgrade to Pro for unlimited loans, branded PDFs, and promissory note generator.”
- “Founder pricing” badge visible in app footer and on PDF/CSV download area.