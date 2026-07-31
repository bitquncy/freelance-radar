# Production operations

## Deployment

**Authoritative deployment checklist**
1. Set `POSTGRES_PASSWORD` outside source control.
2. Set `ENVIRONMENT=production`, `DATABASE_URL=postgresql...`, `BOT_REPLICAS=1`.
3. Run `docker compose up -d --build`.
4. Confirm entrypoint refuses SQLite, waits for PostgreSQL readiness, runs Alembic, then starts one bot replica.
5. Keep `PicklePersistence` single-replica only until a reviewed shared FSM implementation replaces it.

This document is the production source of truth; README should only link here for ops details.

## Backup, restore drill, and retention automation

Choose `RPO_HOURS` and `RTO_HOURS` for the environment (recommended initial targets:
RPO 24h, RTO 4h).

### Backup

Run the logical backup helper on a schedule from a cron runner, CI runner, or an
external job runner that already exists in your deployment. The repository does not
invent new infrastructure; it ships a safe command-ready artifact:

- dry run: `python scripts/backup_db.py --dry-run`
- execution: `python scripts/backup_db.py --confirm RUN-BACKUP`

Use the backup scheduler in the environment that already exists to call the command at
least every RPO interval, then copy dumps encrypted to off-host/object storage and
retain them per legal policy.

### Restore drill

Test restore quarterly in an isolated database using the same operational artifact:

- dry run: `python scripts/restore_db.py backup.dump --dry-run`
- destructive drill: `python scripts/restore_db.py backup.dump --confirm DESTROY-AND-RESTORE`

The restore drill must be run only against an isolated database and only after the
backup file and target URL are verified. Stop the bot before destructive restore,
restore, run `alembic upgrade head`, healthcheck, and a Telegram smoke test.

### Retention

Default database retention is 365 days (`DATA_RETENTION_DAYS`), minimum 30. Preview:
`python scripts/purge_data.py`; execute only after review with `--apply` and
`RETENTION_PURGE_APPROVED=YES`. The purge covers old interactions and raw projects;
subscriptions/payment records are retained for accounting and are deliberately
excluded. Foreign-key constraints may prevent project deletion while dependent
analysis/proposal records remain; review output and legal requirements before
applying. User-request deletion now uses the owner-scoped workflow below.

## Owner-scoped export/delete workflow

The owner-scoped workflow is explicit and two-step:

1. Export a user snapshot in dry-run mode first:
   `python scripts/export_owner_data.py --user-id <USER_ID> --dry-run`
2. When the output and target owner are verified, export for real:
   `python scripts/export_owner_data.py --user-id <USER_ID> --confirm EXPORT-OWNER`
3. Delete the owner-scoped data only after a verified export:
   `python scripts/delete_owner_data.py --user-id <USER_ID> --confirm DELETE-OWNER`

Both commands refuse to run without `DATABASE_URL` pointing at PostgreSQL.
The deletion workflow removes data only for the specified owner and intentionally
keeps subscription/accounting records as required by retention policy and finance.
