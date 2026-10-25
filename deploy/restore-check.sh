#!/bin/sh
# Restore a Fateweave dump into a DISPOSABLE database and print table row counts only.
# Never prints row contents. The disposable database is always dropped afterwards.
#
# Usage: restore-check.sh /path/to/fateweave_<ts>.dump
#
# Credentials: PGPASSFILE or PGPASSWORD in the environment, never on the command line. Connection
# via libpq variables (PGHOST PGPORT PGUSER). The role needs CREATEDB (or be a superuser).
#   PGMAINTDB   database to connect to for CREATE/DROP DATABASE (default: postgres)
set -eu
umask 077

dump="${1:?usage: restore-check.sh /path/to/dump}"
[ -f "$dump" ] || { echo "dump not found: $dump" >&2; exit 2; }
PGMAINTDB="${PGMAINTDB:-postgres}"

ts=$(date -u +%Y%m%d%H%M%S)
db="fateweave_restore_check_${ts}"
created=0

cleanup() {
    if [ "$created" = 1 ]; then
        psql -X -q --no-password -d "$PGMAINTDB" -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" >/dev/null \
            && echo "dropped disposable database $db"
    fi
}
trap cleanup EXIT INT TERM

psql -X -q --no-password -d "$PGMAINTDB" -c "CREATE DATABASE \"$db\""
created=1

# Ownership/ACLs belong to the source cluster's roles; the check only needs the data.
pg_restore --no-password --no-owner --no-privileges --exit-on-error -d "$db" "$dump"

echo "restored $dump into $db; row counts per table:"
psql -X -At --no-password -d "$db" <<'SQL'
SELECT format('SELECT %L AS table_name, count(*) AS row_count FROM %I.%I', tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename
\gexec
SQL
