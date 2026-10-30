# Nightly database backup job (Railway cron service "db-backup"). See README.md.
# pg_dump must be at least the server's major version: production runs Postgres 18.
FROM postgres:18-alpine
RUN apk add --no-cache aws-cli openssl
COPY backup.sh /usr/local/bin/backup.sh
# initdb (used for the restore test) refuses to run as root
USER postgres
# HOME for aws-cli; R2 rejects the newer default S3 checksum headers
ENV HOME=/tmp \
    AWS_DEFAULT_REGION=auto \
    AWS_REQUEST_CHECKSUM_CALCULATION=when_required \
    AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
ENTRYPOINT ["/bin/sh", "/usr/local/bin/backup.sh"]
