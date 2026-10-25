#!/bin/sh
# Logical backup of the Fateweave database (custom format, owner-only permissions).
#
# Credentials: use a PGPASSFILE (mode 600) or PGPASSWORD in the environment. They are never
# placed on the command line. Connection settings come from the standard libpq variables:
#   PGHOST PGPORT PGUSER PGDATABASE PGPASSFILE
#
# Settings (environment):
#   BACKUP_DIR   target directory (required; created 700 if missing)
#   KEEP_DAYS    delete fateweave_*.dump older than this many days (default 14)
#   PGDATABASE   default: fateweave
#
# NOT installed into cron by this repo. Example entry for the operator to add deliberately
# (daily 03:15, `crontab -e` as the backup user):
#   15 3 * * * BACKUP_DIR=/var/backups/fateweave PGHOST=127.0.0.1 PGUSER=fateweave_owner PGPASSFILE=/etc/fateweave/pgpass /opt/fateweave/deploy/backup.sh >>/var/log/fateweave-backup.log 2>&1
#
# Dumps contain birth data: keep them on the VM with restricted access, and copy them off-host
# only to encrypted storage.
set -eu
umask 077

: "${BACKUP_DIR:?BACKUP_DIR must be set}"
KEEP_DAYS="${KEEP_DAYS:-14}"
PGDATABASE="${PGDATABASE:-fateweave}"
export PGDATABASE

case "$KEEP_DAYS" in
    ''|*[!0-9]*) echo "KEEP_DAYS must be a non-negative integer" >&2; exit 2 ;;
esac

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

ts=$(date -u +%Y%m%dT%H%M%SZ)
final="$BACKUP_DIR/fateweave_${ts}.dump"
tmp="$final.partial"
trap 'rm -f "$tmp"' EXIT INT TERM

pg_dump --format=custom --no-password --file="$tmp" "$PGDATABASE"
mv "$tmp" "$final"
chmod 600 "$final"
echo "backup written: $final ($(wc -c < "$final") bytes)"

# Rotation: only our own naming pattern, only regular files, only in BACKUP_DIR.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'fateweave_*.dump' -mtime "+$KEEP_DAYS" -exec rm -f {} +
