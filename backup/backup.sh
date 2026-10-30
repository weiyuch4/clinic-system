#!/bin/sh
# Production backup: dump -> prove it restores -> encrypt -> upload to Cloudflare R2 -> check the upload.
# Exits non-zero on any failure so the Railway run shows as failed.
set -eu
set -o pipefail

for v in DATABASE_URL R2_ENDPOINT R2_BUCKET AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY BACKUP_PASSPHRASE; do
  eval "val=\${$v:-}"
  [ -n "$val" ] || { echo "FAILED: variable $v is not set"; exit 1; }
done
# An invisible character (e.g. a BOM from pasting) would make every backup unopenable with the saved copy
case "$BACKUP_PASSPHRASE" in
  *[!A-Za-z0-9]*) echo "FAILED: BACKUP_PASSPHRASE must be letters and digits only"; exit 1 ;;
esac

WORK=$(mktemp -d)
trap 'pg_ctl -D "$WORK/pg" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
STAMP=$(date -u +%Y-%m-%dT%H%MZ)
KEY="postgres/clinic-$STAMP.dump.enc"

echo "1/4 dumping production"
pg_dump --format=custom --no-owner --no-privileges --file="$WORK/db.dump" "$DATABASE_URL"
echo "    dump: $(wc -c < "$WORK/db.dump" | tr -d ' ') bytes"

echo "2/4 restoring into a throwaway database to prove the dump works"
initdb -D "$WORK/pg" -U postgres --auth=trust >/dev/null
pg_ctl -D "$WORK/pg" -o "-k $WORK -c listen_addresses=''" -w start >/dev/null
if ! pg_restore --no-owner --no-privileges -h "$WORK" -U postgres -d postgres "$WORK/db.dump" 2>"$WORK/restore.err"; then
  echo "FAILED: restore test"; tail -n 20 "$WORK/restore.err"; exit 1
fi
for t in clinics users synced_candidates contacts inventory_items; do
  live=$(psql "$DATABASE_URL" -Atc "SELECT count(*) FROM $t")
  copy=$(psql -h "$WORK" -U postgres -d postgres -Atc "SELECT count(*) FROM $t")
  echo "    $t: live $live, restored $copy"
done
[ "$(psql -h "$WORK" -U postgres -d postgres -Atc 'SELECT count(*) FROM users')" -gt 0 ] || { echo "FAILED: restored copy has no users"; exit 1; }
pg_ctl -D "$WORK/pg" -m fast stop >/dev/null

echo "3/4 encrypting and uploading"
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_PASSPHRASE -in "$WORK/db.dump" -out "$WORK/db.enc"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$WORK/db.enc" | cmp -s - "$WORK/db.dump" \
  || { echo "FAILED: encrypted file doesn't decrypt back to the dump"; exit 1; }
aws s3 cp "$WORK/db.enc" "s3://$R2_BUCKET/$KEY" --endpoint-url "$R2_ENDPOINT" --only-show-errors

echo "4/4 checking the upload"
remote=$(aws s3api head-object --bucket "$R2_BUCKET" --key "$KEY" --endpoint-url "$R2_ENDPOINT" --query ContentLength --output text)
size=$(wc -c < "$WORK/db.enc" | tr -d ' ')
[ "$remote" = "$size" ] || { echo "FAILED: uploaded $remote bytes, expected $size"; exit 1; }

# Optional: a "dead man's switch" URL that alerts when a night's ping doesn't arrive
if [ -n "${HEARTBEAT_URL:-}" ]; then wget -q -O /dev/null "$HEARTBEAT_URL" || echo "warning: heartbeat ping failed"; fi
echo "OK $KEY ($size bytes)"
