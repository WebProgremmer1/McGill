-- Newer Supabase projects don't auto-grant table access to API roles.
-- Give the backend's secret key (service_role) full access to our tables.
-- anon / authenticated (the public, browser-side keys) get nothing.
grant usage on schema public to service_role;
grant select, insert, update, delete on
  public.google_accounts, public.contacts, public.escalations, public.notifications_sent
  to service_role;
alter default privileges in schema public
  grant select, insert, update, delete on tables to service_role;
notify pgrst, 'reload schema';
