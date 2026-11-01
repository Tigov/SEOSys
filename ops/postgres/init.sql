-- Runs once, when the Postgres volume is first created.
-- seosys_owner (POSTGRES_USER) owns the schema and runs migrations.
-- seosys_app is what the application connects as: it owns nothing, so row-level security applies to it.
CREATE ROLE seosys_app LOGIN PASSWORD 'seosys_app_local';

CREATE DATABASE seosys_test OWNER seosys_owner;

GRANT CONNECT ON DATABASE seosys TO seosys_app;
GRANT CONNECT ON DATABASE seosys_test TO seosys_app;

\connect seosys
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO seosys_app;

\connect seosys_test
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO seosys_app;
