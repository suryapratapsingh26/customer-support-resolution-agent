#!/bin/bash
set -euo pipefail

psql --set ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_user="$APP_DB_USER" \
  --set=app_password="$APP_DB_PASSWORD" \
  --set=migration_user="$MIGRATION_DB_USER" \
  --set=migration_password="$MIGRATION_DB_PASSWORD" \
  --set=database_name="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password';
CREATE ROLE :"migration_user" LOGIN PASSWORD :'migration_password';
ALTER SCHEMA public OWNER TO :"migration_user";
GRANT CONNECT ON DATABASE :"database_name" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_user" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_user" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"app_user";
SQL
