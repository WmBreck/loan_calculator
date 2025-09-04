-- migrations.sql (idempotent patches)
alter table if exists public.loans add column if not exists loan_name text;
alter table if exists public.loans add column if not exists late_fee_type text default 'fixed';
alter table if exists public.loans add column if not exists late_fee_amount numeric(14,2) default 0;
alter table if exists public.loans add column if not exists late_fee_days int default 0;
alter table if exists public.loans add column if not exists penalty_interest_rate numeric(9,6);
update public.loans set loan_name = coalesce(loan_name, name) where loan_name is null;

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='payments' and column_name='pay_date'
  ) and not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='payments' and column_name='payment_date'
  ) then
    execute 'alter table public.payments rename column pay_date to payment_date';
  end if;
end$$;

alter table if exists public.payments add column if not exists created_at timestamptz default now();

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'payments_amount_positive'
      and conrelid = 'public.payments'::regclass
  ) then
    alter table public.payments add constraint payments_amount_positive check (amount > 0);
  end if;
end$$;
