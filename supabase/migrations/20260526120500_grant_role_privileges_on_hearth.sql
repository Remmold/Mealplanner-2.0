-- Grant the Supabase-managed roles the privileges they need on the `hearth`
-- schema. Without these, `SET LOCAL role = 'service_role'` (or
-- `'authenticated'`) inside a transaction succeeds at the role switch but
-- every subsequent query against hearth.* dies with
-- `permission denied for schema hearth`.
--
-- - `service_role` has BYPASSRLS, so it gets ALL on every table. The API
--   uses this for cross-row consistency ops (credit ledger writes, image
--   path updates, executor mutations).
-- - `authenticated` gets DML (select/insert/update/delete); RLS policies
--   (in 20260526120300_rls_policies.sql) gate which rows it can actually
--   touch. Without DML grants, even RLS-permitted rows return permission
--   denied.
-- - ALTER DEFAULT PRIVILEGES makes future tables in the schema
--   automatically inherit these grants — saves a re-grant after every
--   schema-additive migration.

-- ============================================================================
-- service_role
-- ============================================================================
grant usage on schema hearth to service_role;
grant all privileges on all tables    in schema hearth to service_role;
grant all privileges on all sequences in schema hearth to service_role;
grant all privileges on all functions in schema hearth to service_role;

alter default privileges in schema hearth
    grant all on tables    to service_role;
alter default privileges in schema hearth
    grant all on sequences to service_role;
alter default privileges in schema hearth
    grant all on functions to service_role;

-- ============================================================================
-- authenticated
-- ============================================================================
grant usage on schema hearth to authenticated;
grant select, insert, update, delete on all tables in schema hearth to authenticated;
grant usage, select on all sequences in schema hearth to authenticated;
grant execute on all functions in schema hearth to authenticated;

alter default privileges in schema hearth
    grant select, insert, update, delete on tables to authenticated;
alter default privileges in schema hearth
    grant usage, select on sequences to authenticated;
alter default privileges in schema hearth
    grant execute on functions to authenticated;
