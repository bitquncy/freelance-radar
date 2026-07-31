# Task for worker

Сделай one-shot sprint implementation в уже dirty worktree без перезаписи пользовательских изменений. Цели: (1) owner-scoped export/delete workflow, (2) автоматизация backup schedule, (3) автоматизация restore drill, (4) CI job на PostgreSQL smoke test. Используй текущие готовые script/docs patterns, не ломай существующие tests. Если что-то уже реализовано, только доведи до production-grade. Нельзя менять secrets и нельзя reset/stash/checkout.

Нужно:
- Реализовать owner-scoped export/delete workflow безопасно и явно, с dry-run/confirm где нужно, плюс документация.
- Добавить автоматизацию/расписание для backup и restore drill (через existing pipe / CI / cron-ready artifacts — выбери безопасный реализуемый вариант без новых инфраструктурных предположений). Если нельзя безопасно автоматизировать fully, создай готовый pipe/CI/script scaffold и docs, но не придумывай несуществующую систему.
- Добавить CI job for PostgreSQL smoke test: TEST_DATABASE_URL-gated, skip cleanly when absent, validate on GitHub Actions if already used.
- Сохранить SQLite dev/test compatibility.
- Добавить/обновить tests.
- В конце выполнить pytest/ruff/mypy/safe script checks; если real PostgreSQL unavailable, clearly mark skipped.

Верни итог: changed files, exact behavior, commands run and exit codes, skipped checks, residual risks, and anything still needing manual ops approval. Не останавливайся на частичном результате, если нет блокера.

## Acceptance Contract
Acceptance level: checked
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Implement the requested change without widening scope

Required evidence: changed-files, tests-added, commands-run, residual-risks, no-staged-files

Finish with a fenced JSON block tagged `acceptance-report` in this shape:
Use empty arrays when no items apply; array fields contain strings unless object entries are shown.
`criteriaSatisfied[].status` must be exactly one of: satisfied, not-satisfied, not-applicable.
`commandsRun[].result` must be exactly one of: passed, failed, not-run.
`manualNotes` and `notes` are optional strings; an empty string means no note and does not satisfy `manual-notes` evidence.
```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "specific proof"
    }
  ],
  "changedFiles": [
    "src/file.ts"
  ],
  "testsAddedOrUpdated": [
    "test/file.test.ts"
  ],
  "commandsRun": [
    {
      "command": "command",
      "result": "passed",
      "summary": "short result"
    }
  ],
  "validationOutput": [
    "validation output or concise summary"
  ],
  "residualRisks": [
    "none"
  ],
  "noStagedFiles": true,
  "diffSummary": "short description of the diff",
  "reviewFindings": [
    "blocker: file.ts:12 - issue found, or no blockers"
  ],
  "manualNotes": "anything else the parent should know"
}
```