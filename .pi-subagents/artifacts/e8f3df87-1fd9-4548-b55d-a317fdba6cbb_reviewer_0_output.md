## Review

- **Correct:** Current payment idempotency has a database-backed unique constraint on `subscriptions.payment_charge_id` (`core/models.py:382-396`, migration `alembic/versions/d4f51504d763_telegram_payments_charge_id.py:21-32`). This correctly suppresses redelivery of the **same** charge ID.
- **Correct:** Project ingestion already has a unique `(source, external_id)` constraint (`core/models.py:211-224`), so basic listing idempotency is database-enforced.
- **Correct:** Reminder polling has an appropriate `(status, due_at)` index (`core/models.py:341-357`), but the subsequent claim is not atomic.
- **Correct:** The dirty worktree was inspected without modification. There are no staged files, and all existing user changes remain intact.
- **Note:** The requested `plan.md` and `progress.md` do not exist at the specified repository paths. Planning therefore used the current worktree and `PROJECT_AUDIT_2026-07-31.md`.
- **Note:** No project-local `.pi/skills` directory exists, so no screenpipe skill files were available to read. Screenpipe data was not needed for this task.

### Blocker — concurrent distinct payments lose paid time

**Severity: HIGH**

**Evidence:** `core/billing.py:120-128` computes the new expiry from the caller-supplied `User` instance before obtaining any row lock. `core/billing.py:140-164` inserts the payment and writes the computed expiry, while `bot/handlers/v2/payments.py:154-164` commits afterward. Two transactions with different valid charge IDs can both read the same old expiry and both write `old_expiry + 30 days`.

#### Exact proposed changes

1. Change `apply_paid_subscription()` so it does not rely on an unlocked caller-owned `User` snapshot:
   - Acquire the user row inside the active transaction with:
     ```python
     select(User).where(User.id == user.id).with_for_update()
     ```
   - Compute `base` and `period_end` from that locked row.
   - Insert `Subscription` and update the locked `User` in the same transaction.
   - Return the locked/current user expiry or expose it via the returned result; do not read expiry from the possibly stale handler instance after the call.

2. Preserve charge idempotency:
   - Keep `uq_subscriptions_charge`.
   - Under the user lock, check for an existing charge before applying the extension.
   - Retain the unique constraint and `IntegrityError` recovery as the final cross-process defense.

3. Define lock order explicitly:
   - Always lock `User` first, then insert/read `Subscription`.
   - Do not introduce another path that locks subscription first and user second, or payment processing could deadlock.

4. Prefer loading the user by ID inside billing over accepting a mutable ORM object. A bounded API would be:
   ```python
   apply_paid_subscription(session, user_id, intent, charge_id, provider=...)
   ```
   This prevents future callers from accidentally bypassing the lock discipline.

5. Keep transaction ownership at the handler level:
   - `apply_paid_subscription()` should flush, not commit.
   - `bot/handlers/v2/payments.py` should continue committing payment record and entitlement together.

#### Migration/constraint need

- No new payment constraint is required; `uq_subscriptions_charge` is the correct idempotency key.
- Before production rollout, verify no duplicate non-null charge IDs exist so the existing migration remains deployable.
- Optional hardening: add `CHECK (period_end >= period_start)` and provider-scoped uniqueness only if charge IDs are not globally unique across future providers. Do **not** change the existing key without confirming Telegram/YooKassa identifier semantics.

#### SQLite versus PostgreSQL

- PostgreSQL `SELECT ... FOR UPDATE` serializes updates to the same user row.
- SQLite ignores/does not provide equivalent row-level `FOR UPDATE` behavior and serializes writes differently, so SQLite tests cannot prove this fix.
- SQLite unit tests can verify sequential extension and duplicate-charge behavior only.
- Production correctness must be gated by a real PostgreSQL test.

---

### Blocker — reminder claim is not atomic

**Severity: HIGH**

**Evidence:** `_claim_due_reminder()` loads the row with `session.get()` at `monitoring/worker.py:477-480`, checks PENDING, then changes it at `monitoring/worker.py:496-498`. Two sessions can both pass the check and both return a claimed tuple. The docstring’s “Atomically” and “at-most-once” assertions are therefore false.

#### Exact proposed changes

Use a single conditional DML claim:

```sql
UPDATE reminders
SET status = 'notified'
WHERE id = :id
  AND status = 'pending'
  AND due_at <= :now
RETURNING id, client_id, due_at, message, status, created_at
```

Implementation details:

1. Execute SQLAlchemy `update(Reminder)` with all eligibility predicates and `.returning(Reminder)`.
2. If no row is returned, return `None`; another worker won or the reminder is no longer eligible.
3. Load `Client` and `User` only after successfully claiming.
4. Keep the claim commit before Telegram send if the intentionally chosen contract remains at-most-once.
5. For orphaned/ineligible users:
   - Prefer a separate conditional transition from PENDING to DONE/CANCELLED.
   - If eligibility is discovered after the row became NOTIFIED, transition it to DONE in the same transaction before commit, so it does not appear as delivered.
6. Include `due_at <= now` in the claim itself. The current outer due-ID scan is only a work-discovery optimization and must not establish eligibility.

An alternative bulk worker design is `SELECT ... FOR UPDATE SKIP LOCKED LIMIT N`, then update and commit claimed rows. For the current one-ID-at-a-time API, conditional `UPDATE ... RETURNING` is simpler and avoids holding locks while loading related rows.

#### Migration/constraint need

- No schema change is required for atomic claim.
- Existing `ix_reminders_status_due` supports the claim predicate.
- Optional operational fields such as `claimed_at`, `claim_token`, `attempt_count`, and `last_error` would require migration but are not needed for strict commit-before-send semantics.

#### Delivery compatibility risk

The current at-most-once model commits before calling Telegram (`monitoring/worker.py:506-510`). It prevents retries after a successful atomic claim but loses a notification if the process crashes or Telegram rejects the send. Atomic claim fixes duplicate sends, not this loss window.

If eventual delivery is required, introduce an outbox/delivery record with a unique reminder ID and retry states rather than reverting status after send failure. Exactly-once external delivery is impossible without cooperation from Telegram; the practical target is idempotent durable dispatch.

---

### Blocker — TG-channel duplicate and quota checks race

**Severity: MEDIUM**

**Evidence:** `bot/handlers/v2/sources.py:220-238` reads all channels, checks normalized values and count in application code, then inserts at `:239-246`. `core/models.py:178-190` intentionally excludes TG channels from its only connection uniqueness index. Concurrent requests can both pass duplicate and quota checks.

#### Exact proposed changes

1. Add a stored normalized key to `ExchangeConnection`, for example:
   ```python
   channel_normalized: Mapped[Optional[str]] = mapped_column(String(255))
   ```
2. Centralize normalization:
   - Strip whitespace.
   - Accept `@name`, `t.me/name`, and supported Telegram URL variants.
   - Remove query strings/trailing slash.
   - Normalize username case with `casefold()` and persist a canonical representation such as lowercase without `@`.
   - Explicitly decide whether private invite links and numeric channel IDs are supported. A username-only key cannot safely deduplicate private links.
3. Add a partial unique index for TG rows:
   ```sql
   UNIQUE (user_id, channel_normalized)
   WHERE platform = 'tg_channel'
   ```
4. On insert, catch `IntegrityError` and return the existing duplicate-channel response.
5. Serialize quota allocation by locking the owning user:
   ```python
   select(User).where(User.id == user_id).with_for_update()
   ```
   Then count TG connections and insert while the lock is held.
6. Apply the same user-lock convention to all paths that consume per-user source quota. A lock is only effective if every allocating path takes it.
7. Keep validation and normalization outside the lock where possible; acquire the lock immediately before final count/insert to minimize contention.

A pure unique constraint fixes duplicates but **not** the finite quota. A pure user lock fixes quota only if every writer honors it, so both mechanisms are needed.

#### Migration/constraint need

Create a new Alembic revision after the current head:

1. Add nullable `channel_normalized`.
2. Backfill TG rows from `settings["channel"]`.
   - PostgreSQL JSON extraction: `settings ->> 'channel'`.
   - Do normalization in deterministic migration code or SQL.
3. Detect collisions before adding the unique index.
   - Do not silently delete user connections.
   - Fail migration with a clear report, or ship a separate pre-migration cleanup command reviewed by the owner.
4. Add the partial unique index.
5. Optionally add a check:
   ```sql
   platform = 'tg_channel' AND channel_normalized IS NOT NULL
   OR platform <> 'tg_channel' AND channel_normalized IS NULL
   ```
   This is useful but increases migration compatibility work.

#### SQLite versus PostgreSQL

- Both dialects support partial indexes in the project’s supported versions, so define both `sqlite_where` and `postgresql_where`.
- SQLite and PostgreSQL must receive the same normalized stored value; do not depend on database collation or `lower()` uniqueness. SQLite `NOCASE` is ASCII-oriented, and PostgreSQL collation/case behavior differs.
- PostgreSQL user-row locking proves quota serialization.
- SQLite does not emulate row-level locks and may instead emit `database is locked`; SQLite unit tests cannot attest the quota race fix.

---

### Note — idempotency boundaries

**Severity: MEDIUM**

1. **Payment:** Unique charge ID is correct, but duplicate handling should verify the existing row belongs to the same user and has matching amount/tier/provider before returning `applied=False`. A charge collision with mismatched metadata should raise and trigger reconciliation, not be described as a harmless duplicate (`core/billing.py:144-158`).
2. **Reminder:** Status transition is the idempotency key. Make it conditional in the database.
3. **TG channel:** The normalized channel key must be database-unique per user.
4. **Quota:** Quota is an invariant, not an idempotency key; enforce it through serialized allocation.
5. **Payment response after commit:** Telegram reply failure can cause the user to see no confirmation, but the unique charge ID makes handler redelivery safe. The duplicate response should reflect the authoritative stored subscription.
6. **External side effects:** Do not hold PostgreSQL row locks across Telegram network calls.

## Focused test plan

### SQLite unit tests

Add or update focused tests without claiming concurrency coverage:

- `tests/unit/v2/test_v2_payments.py`
  - Sequential distinct same-tier charges extend by exactly 60 days.
  - Same charge twice produces one `Subscription` and one extension.
  - Duplicate charge with mismatched user/tier/amount is rejected or escalated.
  - Tier-switch semantics remain intentional and tested.
- New reminder claim tests, likely in `tests/unit/v2/test_v2_worker_concurrency.py`
  - First conditional claim returns data and sets NOTIFIED.
  - Second claim returns `None`.
  - Future, DONE, CANCELLED, and missing reminder IDs are not claimed.
  - Ineligible/orphaned reminder ends in the chosen terminal state.
- Source tests in `tests/unit/v2/test_v2_handlers.py` or a dedicated source test:
  - Equivalent forms such as `@Foo`, `https://t.me/foo/`, and `foo` normalize identically.
  - Duplicate insert maps `IntegrityError` to the existing user-facing message.
  - Backfill normalization behavior is covered as a pure function.

### True PostgreSQL concurrency tests

Expand or split `tests/integration/test_postgres_smoke.py`. Its current test is sequential and explicitly skips unless `TEST_PG_URL` is set (`tests/integration/test_postgres_smoke.py:1-12,27-29`), so it does not satisfy the concurrency requirement.

Use two independent `AsyncSession`s backed by an engine pool with at least two connections. Coordinate starts with `asyncio.Event`/barriers and enforce timeouts to avoid hanging CI.

1. **Concurrent distinct payments**
   - Create one paid PRO user with fixed expiry.
   - Start transaction A and B with different charge IDs.
   - Ensure both enter payment processing concurrently.
   - Commit both.
   - Assert:
     - two subscription rows,
     - final user expiry equals original expiry + 60 days,
     - neither transaction failed.
   - Repeat enough times to expose an unlocked implementation, or use a test hook/barrier after initial row acquisition to make the race deterministic.

2. **Concurrent duplicate payment**
   - Same user, same charge ID, two sessions.
   - Assert one subscription, exactly one `applied=True`, one `applied=False`, and only one 30-day extension.
   - Verify the losing transaction remains usable after savepoint recovery.

3. **Concurrent reminder claim**
   - One due PENDING reminder.
   - Two sessions call `_claim_due_reminder()` concurrently.
   - Assert exactly one non-null result and one NOTIFIED row.
   - Invoke two concurrent `run_reminders_tick()` calls with a shared counting fake notifier; assert one notification call.

4. **Concurrent duplicate channel**
   - Same user, equivalent normalized channel representations, two sessions.
   - Assert one insert succeeds, one gets the duplicate outcome, and only one row exists.

5. **Concurrent final quota slot**
   - Seed `limit - 1` TG channels.
   - Concurrently add two different channels.
   - Assert only one succeeds and total count equals the limit.
   - This test must exercise the actual service/handler allocation helper, not merely raw inserts, because quota is lock-protocol-enforced rather than constrained by DDL.

6. **Migration verification**
   - Upgrade a clean PostgreSQL database to head.
   - Verify index predicates using `pg_indexes`.
   - Seed legacy TG data, run the new revision, and verify backfill.
   - Explicitly test collision handling with canonical-equivalent legacy rows.

### CI requirement

- Provision PostgreSQL as a CI service and make these tests non-optional in the production gate.
- Use a dedicated empty database/schema per test worker.
- Do not run concurrent tests against a shared developer database.
- Run Alembic upgrade before tests.
- Keep SQLite unit tests fast, but do not accept them as evidence for PostgreSQL locking semantics.

## Compatibility risks

- **Stale ORM instances:** Re-loading/locking a `User` while another instance with the same identity exists in the session needs careful use of `populate_existing=True`, `session.refresh(..., with_for_update=True)`, or a billing API based on `user_id`.
- **Deadlocks:** Inconsistent lock ordering between payment, channel allocation, and future user mutations can deadlock. Standardize on user row first.
- **Long transactions:** Telegram calls must remain outside locked transactions.
- **Migration collisions:** Existing TG duplicates may prevent unique-index creation; migration must report rather than silently destroy data.
- **Normalization changes:** Future normalization rules could turn previously distinct channel values into collisions. Treat canonicalization as persisted schema behavior and version changes carefully.
- **Private Telegram channels:** Username normalization does not cover invite hashes or resolved numeric IDs. Define support before selecting the canonical key.
- **SQLite behavior:** SQLite may pass all sequential tests while PostgreSQL-specific locking code remains broken; conversely, SQLite can raise lock errors not representative of PostgreSQL row locking.
- **Naive timestamps:** Models use `DateTime` without timezone (`core/models.py:152,352,397-399`). Preserve existing UTC-naive convention during this focused fix; a timezone migration would be separate scope.
- **At-most-once loss window:** Atomic claim prevents duplicate reminder sends but retains crash-before-send loss.
- **Existing dirty worktree:** Relevant files already contain user modifications, especially `core/billing.py`, `core/models.py`, `monitoring/worker.py`, and `bot/handlers/v2/sources.py`. Implementation must layer minimal edits onto those exact versions, not restore from HEAD.