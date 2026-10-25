-- Fateweave PostgreSQL bootstrap TEMPLATE. Run by a DBA (superuser) on the EXISTING instance:
--
--   psql -X -v ON_ERROR_STOP=1 -v owner_pw='...' -v app_pw='...' \
--        -d postgres -f deploy/postgres-init.sql
--
-- Pass passwords through a protected shell (not shell history); this file contains no secrets.
-- Requires PostgreSQL 15+ (public schema is not world-creatable). It is idempotent: run it a
-- first time BEFORE migrations, run the migrations as fateweave_owner, then run it AGAIN so the
-- table-specific grants below (section 4) apply to the migrated tables.
--
-- Roles
--   fateweave_owner  owns database `fateweave`; used ONLY for `alembic upgrade head` and the
--                    admin purge CLI (python -m fateweave.admin purge-profile). Never in the app env.
--   fateweave_app    runtime role used by the API container: LOGIN, DML only, no DDL, no TRUNCATE,
--                    no CREATE on schema.
--
-- Privilege model for the app role (verified against src/fateweave/storage/repository.py):
--   birth_profiles               SELECT, INSERT                 (rows are never updated by the app)
--   analysis_runs                SELECT, INSERT, UPDATE         (status/attempt updates, SELECT ... FOR UPDATE)
--   report_versions              SELECT, INSERT   (no UPDATE/DELETE)
--   alternative_interpretations  SELECT, INSERT   (no UPDATE/DELETE)
--   alembic_version             no access (owner only)
--   No DELETE anywhere: the only deletes are in the purge CLI, which runs as fateweave_owner.
--   No sequences exist today (UUID keys); default privileges still grant sequence USAGE so a
--   future serial/identity column works.
--
-- LIMITATION: the immutability triggers on report_versions / alternative_interpretations are
-- bypassed when `fateweave.maintenance` = 'on', and ANY role can run `SET fateweave.maintenance`.
-- Immutability against the app role therefore ultimately relies on that role lacking UPDATE and
-- DELETE on those two tables, which this file enforces. Do not widen those grants.

\set ON_ERROR_STOP on

-- 1. Roles (created once; passwords are (re)set on every run).
SELECT format('CREATE ROLE fateweave_owner LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'owner_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fateweave_owner') \gexec
SELECT format('CREATE ROLE fateweave_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT CONNECTION LIMIT 20', :'app_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fateweave_app') \gexec
SELECT format('ALTER ROLE fateweave_owner PASSWORD %L', :'owner_pw') \gexec
SELECT format('ALTER ROLE fateweave_app PASSWORD %L', :'app_pw') \gexec

-- 2. Database owned by fateweave_owner.
SELECT 'CREATE DATABASE fateweave OWNER fateweave_owner ENCODING ''UTF8'''
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'fateweave') \gexec

-- Only these two roles (plus superusers) may connect.
REVOKE ALL ON DATABASE fateweave FROM PUBLIC;
GRANT CONNECT ON DATABASE fateweave TO fateweave_owner, fateweave_app;

-- Hardening guidance for OTHER projects' databases (do NOT run blindly; review each one with its
-- owner first, and never touch a database that belongs to another service without their approval):
--   REVOKE CONNECT ON DATABASE <other_db> FROM PUBLIC;
--   GRANT  CONNECT ON DATABASE <other_db> TO <that_project_role>;
-- fateweave_app/fateweave_owner have no grants in any other database; the REVOKE above only
-- matters when a database still carries the default PUBLIC CONNECT privilege. After applying,
-- verify with:  psql -U fateweave_app -d <other_db>   (expect: permission denied)

-- 3. Schema and default privileges inside the fateweave database.
\connect fateweave

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO fateweave_owner;
GRANT USAGE ON SCHEMA public TO fateweave_app;   -- USAGE only: no CREATE

-- Tables created later by the owner (migrations) get the SAFE baseline for the app role.
ALTER DEFAULT PRIVILEGES FOR ROLE fateweave_owner IN SCHEMA public
    GRANT SELECT, INSERT ON TABLES TO fateweave_app;
ALTER DEFAULT PRIVILEGES FOR ROLE fateweave_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO fateweave_app;

-- 4. Table-specific grants. Re-run this file after migrations so existing tables are covered.
--    Existing tables: baseline SELECT, INSERT (covers tables created before default privileges).
DO $$
DECLARE t text;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tableowner = 'fateweave_owner'
    LOOP
        EXECUTE format('GRANT SELECT, INSERT ON public.%I TO fateweave_app', t);
        EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.%I FROM fateweave_app', t);
    END LOOP;
    -- Alembic bookkeeping is owner-only: the runtime role must not read or write it.
    IF to_regclass('public.alembic_version') IS NOT NULL THEN
        REVOKE ALL ON public.alembic_version FROM fateweave_app;
    END IF;
    -- Mutable operational table: status transitions and attempt counters.
    IF to_regclass('public.analysis_runs') IS NOT NULL THEN
        GRANT UPDATE ON public.analysis_runs TO fateweave_app;
    END IF;
    -- Immutable records: never UPDATE/DELETE for the app role.
    IF to_regclass('public.report_versions') IS NOT NULL THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON public.report_versions FROM fateweave_app;
    END IF;
    IF to_regclass('public.alternative_interpretations') IS NOT NULL THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON public.alternative_interpretations FROM fateweave_app;
    END IF;
END
$$;
