# Database backups

Railway cron service **db-backup** (production environment) runs `backup.sh` every night at 03:00 Taiwan time (`0 19 * * *` UTC):

1. `pg_dump` the production database (custom format)
2. restore it into a throwaway Postgres inside the container and compare row counts — a backup that doesn't restore fails the run
3. encrypt with AES-256 (`BACKUP_PASSPHRASE`) and upload to Cloudflare R2 bucket `clinic-db-backups` as `postgres/clinic-<UTC time>.dump.enc`
4. check the uploaded size matches

R2 deletes copies older than 60 days (bucket lifecycle rule `keep-60-days`). A failed run shows as failed in Railway → db-backup → Deployments.

Variables on the service: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `R2_ENDPOINT`, `R2_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (R2 account token limited to this bucket), `BACKUP_PASSPHRASE`, optional `HEARTBEAT_URL`.

**`BACKUP_PASSPHRASE` is the only way to open the backups. Keep a copy outside Railway (password manager).** Losing it makes every backup useless; changing it only affects new backups.

## Deploying changes to the job

The service is deployed from this folder, not from GitHub:

```
railway up backup --path-as-root --service db-backup --environment production
```

Run it once by hand: Railway → db-backup → the latest deployment → ⋯ → Redeploy (or wait for 03:00).

## Restoring

Never restore into staging (staging holds fake data only).

1. Download a copy (Cloudflare dashboard → R2 → clinic-db-backups → postgres/ → Download), or with the AWS CLI:
   `aws s3 cp s3://clinic-db-backups/postgres/<file> . --endpoint-url <R2_ENDPOINT>`
2. Decrypt (asks nothing; reads the passphrase from the environment variable):
   ```
   BACKUP_PASSPHRASE='…' openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in <file>.dump.enc -out clinic.dump
   ```
3. Restore with Postgres 18 tools into an **empty** database (a new Railway Postgres service, never the live one until you're sure):
   ```
   pg_restore --no-owner --no-privileges -d "<new DATABASE_URL>" clinic.dump
   ```
4. Point the app at it only after checking the data: change `web`'s `DATABASE_URL` and redeploy.
