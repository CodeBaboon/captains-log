#!/usr/bin/env bash
# Weekly backup of the Captain's Log database.
#
# Uses Python's sqlite3 backup API rather than the sqlite3 command line tool,
# which is not installed on Raspberry Pi OS by default. Python is already a
# requirement, so this adds nothing to install.
#
# A plain cp would be wrong: the database runs in WAL mode, so recent writes
# can be sitting in the write-ahead log rather than the main file. The backup
# API takes a consistent snapshot of a live database without stopping the
# service.
#
# Scoresheet photos are not stored, so the database is the whole of it.

set -euo pipefail

DB="${CC_DB:-/var/lib/captains-log/captains_log.db}"
DEST="${CC_BACKUP_DIR:-/var/backups/captains-log}"
KEEP="${CC_BACKUP_KEEP:-8}"
PY="${CC_PYTHON:-python3}"

mkdir -p "$DEST"
out="$DEST/captains-log-$(date +%Y-%m-%d).db"

"$PY" - "$DB" "$out" <<'PYTHON'
import sqlite3
import sys

source_path, destination_path = sys.argv[1], sys.argv[2]

source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
destination = sqlite3.connect(destination_path)
with destination:
    source.backup(destination)
source.close()

# A backup that cannot be opened is not a backup.
check = destination.execute("PRAGMA integrity_check").fetchone()[0]
games = destination.execute("SELECT COUNT(*) FROM games").fetchone()[0]
destination.close()

if check != "ok":
    sys.exit(f"Backup failed its integrity check: {check}")
print(f"{games} games")
PYTHON

gzip -f "$out"

# Keep the most recent few and drop the rest.
ls -1t "$DEST"/captains-log-*.db.gz 2>/dev/null \
    | tail -n +$((KEEP + 1)) \
    | xargs -r rm --

echo "Backed up to $out.gz"
