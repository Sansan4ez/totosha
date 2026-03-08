-- Supabase: public (anon) read-only setup for a public bot/search
--
-- Goal:
-- - Use ONLY the project "anon/public" key in Totosha (store it in SUPABASE_KEY; never service_role).
-- - Make DB read-only for public access: SELECT-only, no INSERT/UPDATE/DELETE.
-- - Enable RLS so future tables don't accidentally become writable.
--
-- How to use:
-- 1) Open Supabase Dashboard → SQL editor
-- 2) Paste and run this file (review table list first)
-- 3) Test using the anon key via REST: /rest/v1/<table>?select=*&limit=1
--
-- Notes:
-- - This is intentionally minimal and predictable.
-- - If you want to restrict *which* data is readable (not just read-only),
--   replace `using (true)` with a strict predicate (e.g., `is_active = true`).

begin;

-- 0) (Optional) Hard caps for public traffic (recommended for public bots)
--    These settings apply to the DB role used by PostgREST for anon requests.
--    Tune to your workload.
--
-- NOTE: `pgrst.db_max_rows` is used by PostgREST as a server-side max rows cap.
-- alter role anon set pgrst.db_max_rows = '50';
-- alter role anon set statement_timeout = '3s';

-- 1) Choose which tables are exposed publicly
--    Keep this list explicit to avoid surprises.
--
-- If some tables do not exist in your project, remove them from the script.
-- If you have more tables, add them explicitly.

-- === catalog_lamps ===
alter table if exists public.catalog_lamps enable row level security;
drop policy if exists anon_read on public.catalog_lamps;
create policy anon_read on public.catalog_lamps
  for select to anon
  using (true);
revoke insert, update, delete on table public.catalog_lamps from anon, authenticated;

-- === categories ===
alter table if exists public.categories enable row level security;
drop policy if exists anon_read on public.categories;
create policy anon_read on public.categories
  for select to anon
  using (true);
revoke insert, update, delete on table public.categories from anon, authenticated;

-- === etm_oracl_catalog_sku ===
alter table if exists public.etm_oracl_catalog_sku enable row level security;
drop policy if exists anon_read on public.etm_oracl_catalog_sku;
create policy anon_read on public.etm_oracl_catalog_sku
  for select to anon
  using (true);
revoke insert, update, delete on table public.etm_oracl_catalog_sku from anon, authenticated;

-- === etm_oracl_archive ===
alter table if exists public.etm_oracl_archive enable row level security;
drop policy if exists anon_read on public.etm_oracl_archive;
create policy anon_read on public.etm_oracl_archive
  for select to anon
  using (true);
revoke insert, update, delete on table public.etm_oracl_archive from anon, authenticated;

-- === portfolio ===
alter table if exists public.portfolio enable row level security;
drop policy if exists anon_read on public.portfolio;
create policy anon_read on public.portfolio
  for select to anon
  using (true);
revoke insert, update, delete on table public.portfolio from anon, authenticated;

-- === spheres ===
alter table if exists public.spheres enable row level security;
drop policy if exists anon_read on public.spheres;
create policy anon_read on public.spheres
  for select to anon
  using (true);
revoke insert, update, delete on table public.spheres from anon, authenticated;

-- === series ===
alter table if exists public.series enable row level security;
drop policy if exists anon_read on public.series;
create policy anon_read on public.series
  for select to anon
  using (true);
revoke insert, update, delete on table public.series from anon, authenticated;

-- 2) (Optional) Remove write privileges completely (defense in depth).
--    Commented out by default to avoid breaking your existing server-side apps.
--
-- revoke all on all tables in schema public from anon;
-- revoke all on all sequences in schema public from anon;
-- revoke all on all functions in schema public from anon;
-- grant select on all tables in schema public to anon;

commit;

-- Quick tests (run as SQL in editor, not via REST):
-- - Ensure RLS is enabled:
--   select tablename, rowsecurity from pg_tables where schemaname='public' and tablename in (...);
--
-- - Check policies exist:
--   select * from pg_policies where schemaname='public' and policyname='anon_read';
