# Backup and Restore Runbook

## Backup
1. Run daily scheduled job to execute `infra/scripts/backup.sh`.
2. Store dumps in encrypted object storage with 30-day retention.
3. Verify dump by test restore weekly.

## Restore
1. Stop API and worker services.
2. Run `infra/scripts/restore.sh <backup.sql>` against target DB.
3. Start services and run smoke checks (`/health`, basic queries).
4. Log restore event in admin audit history.

## RPO/RTO
- Target RPO: 24 hours
- Target RTO: 2 hours
