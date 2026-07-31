Implemented owner-scoped export/delete workflow, safer backup/restore operational scripts, production ops docs, and a gated PostgreSQL smoke CI job without touching secrets or resetting the dirty tree.

Changed files:
- `.github/workflows/ci.yml`
- `docs/PRODUCTION_OPERATIONS.md`
- `scripts/backup_db.py`
- `scripts/restore_db.py`
- `scripts/export_owner_data.py`
- `scripts/delete_owner_data.py`
- `scripts/purge_data.py`
- `tests/unit/test_scripts.py`
- `tests/integration/test_owner_workflow.py`

Validation:
- `python -m py_compile scripts/backup_db.py scripts/restore_db.py scripts/export_owner_data.py scripts/delete_owner_data.py scripts/purge_data.py tests/unit/test_scripts.py tests/integration/test_owner_workflow.py` → passed
- `python -m ruff check .` → passed
- `python -m mypy --ignore-missing-imports .` → passed
- `python -m pytest tests/unit/test_scripts.py -v` → passed
- `python -m pytest tests/ -v --tb=short` → not fully run here because PostgreSQL-specific/integration coverage was not executed in this environment after the initial unit pass; the owner-script unit coverage passed.
- `pytest` shell command was unavailable in PATH; used `python -m pytest` instead.
- Real PostgreSQL smoke checks were not run because no real TEST_DATABASE_URL-backed Postgres was available in this environment.

Open risks/questions:
- The owner export workflow currently exports owner-owned entities plus globally scoped projects for context; if you want strict per-owner project filtering, that needs a product decision on how to map projects to owners in the existing schema.
- Deletion intentionally preserves subscription/accounting records; if finance/legal wants those removed too, that needs explicit approval.
- CI smoke job is gated on `TEST_DATABASE_URL`; if GitHub Actions secrets are not configured, the job will skip/fail by design depending on runner config.
- Existing dirty worktree changes were preserved; I did not normalize or overwrite unrelated files.

Recommended next step:
- Add `TEST_DATABASE_URL` in GitHub Actions secrets and run the PostgreSQL smoke job once against a real Postgres service; then, if desired, tighten the export/delete owner scope to project ownership semantics after schema/product approval.