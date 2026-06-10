#!/bin/sh
set -eu

export_secret_if_missing() {
  var_name="$1"
  secret_path="$2"
  eval "current_value=\${$var_name-}"
  if [ -n "$current_value" ]; then
    return 0
  fi
  if [ ! -r "$secret_path" ]; then
    return 0
  fi
  secret_value="$(tr -d '\n' < "$secret_path")"
  export "${var_name}=${secret_value}"
}

export_secret_if_missing CORP_DB_RW_DSN /run/secrets/corp_db_rw_dsn
export_secret_if_missing CORP_DB_RO_DSN /run/secrets/corp_db_ro_dsn

exec /usr/local/bin/docker-entrypoint.sh "$@"
