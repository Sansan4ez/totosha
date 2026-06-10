#!/bin/sh
set -eu

read_secret_or_env() {
  env_name="$1"
  secret_path="$2"
  eval "value=\${$env_name-}"
  if [ -n "$value" ]; then
    printf '%s' "$value"
    return 0
  fi
  if [ -r "$secret_path" ]; then
    tr -d '\n' < "$secret_path"
    return 0
  fi
  return 1
}

parse_user() {
  dsn="$1"
  dsn="${dsn#postgresql://}"
  dsn="${dsn#postgres://}"
  printf '%s' "${dsn%%:*}"
}

parse_password() {
  dsn="$1"
  dsn="${dsn#postgresql://}"
  dsn="${dsn#postgres://}"
  dsn="${dsn#*:}"
  printf '%s' "${dsn%%@*}"
}

sql_escape_literal() {
  printf '%s' "$1" | sed "s/'/''/g"
}

RW_DSN="$(read_secret_or_env CORP_DB_RW_DSN /run/secrets/corp_db_rw_dsn)"
RO_DSN="$(read_secret_or_env CORP_DB_RO_DSN /run/secrets/corp_db_ro_dsn)"

RW_USER="$(parse_user "$RW_DSN")"
RW_PASSWORD="$(parse_password "$RW_DSN")"
RO_USER="$(parse_user "$RO_DSN")"
RO_PASSWORD="$(parse_password "$RO_DSN")"

if [ -z "$RW_USER" ] || [ -z "$RW_PASSWORD" ] || [ -z "$RO_USER" ] || [ -z "$RO_PASSWORD" ]; then
  echo "ERROR: failed to parse corp DB DSN secrets" >&2
  exit 1
fi

if [ "$RW_USER" != "corp_rw" ] || [ "$RO_USER" != "corp_ro" ]; then
  echo "ERROR: corp DB DSNs must use fixed role names corp_rw / corp_ro" >&2
  exit 1
fi

RW_PASSWORD_SQL="$(sql_escape_literal "$RW_PASSWORD")"
RO_PASSWORD_SQL="$(sql_escape_literal "$RO_PASSWORD")"

psql -v ON_ERROR_STOP=1 \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'corp_rw') THEN
        CREATE ROLE corp_rw LOGIN PASSWORD '${RW_PASSWORD_SQL}';
    ELSE
        ALTER ROLE corp_rw WITH LOGIN PASSWORD '${RW_PASSWORD_SQL}';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'corp_ro') THEN
        CREATE ROLE corp_ro LOGIN PASSWORD '${RO_PASSWORD_SQL}';
    ELSE
        ALTER ROLE corp_ro WITH LOGIN PASSWORD '${RO_PASSWORD_SQL}';
    END IF;
END \$\$;
SQL

psql -v ON_ERROR_STOP=1 \
  --username "${POSTGRES_USER}" \
  --dbname "${POSTGRES_DB}" \
  -f /docker-entrypoint-initdb.d/20-init.sql.tmpl
