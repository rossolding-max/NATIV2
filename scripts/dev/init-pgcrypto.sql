-- Enable pgcrypto for column-level encryption (per docs/architecture.md § 1).
-- Mounted into postgres container at /docker-entrypoint-initdb.d/ via docker-compose.yml.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
