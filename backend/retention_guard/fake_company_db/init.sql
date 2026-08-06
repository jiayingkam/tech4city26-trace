-- Seeds this throwaway "fake company" database with one inactive and one
-- active sample customer, so a fresh `docker compose ... up` always has
-- something for a demo scan (e.g. inactive_days: 180) to actually find,
-- with no manual setup step. Postgres only runs files under
-- /docker-entrypoint-initdb.d/ once, on first container init against an
-- empty data directory (see docker-compose-retention.yml's mount) — wipe
-- the fake_company_db_data volume (`docker compose ... down -v`) to
-- re-seed from scratch.
CREATE TABLE customers (
  id TEXT PRIMARY KEY,
  email TEXT,
  phone TEXT,
  last_login_at TIMESTAMPTZ,
  notes TEXT
);

INSERT INTO customers (id, email, phone, last_login_at, notes) VALUES
  ('cust-1', 'alice@fakecorp.com', '555-1111', now() - interval '400 days', 'vip'),
  ('cust-2', 'bob@fakecorp.com', '555-2222', now() - interval '5 days', NULL),
  ('cust-3', 'charlie@fakecorp.com', '555-3333', now() - interval '10 days', NULL),
  ('cust-4', 'dave@fakecorp.com', '555-4444', now() - interval '250 days', NULL),
  ('cust-5', 'eric@fakecorp.com', '555-5555', now() - interval '300 days', NULL);
