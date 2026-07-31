# Task for reviewer

Проведи комплексный read-only аудит проекта C:/Users/Пользователь/Desktop/freelance-radar по всем пунктам пользователя: runtime/критические ошибки; PostgreSQL/транзакции; race conditions/double booking; callback-data spoofing; FSM; user/admin/owner permissions; slot locks; waitlist; reminders; backup/restore; migrations; idempotency; payments/bonus spend; error handlers; Telegram API; HTML/Markdown injection; emoji/rendering; .env/secrets; Docker; healthcheck; logging; retention; tests/coverage; production config; parallel-only bugs. Учитывай, что worktree уже содержит пользовательские незакоммиченные изменения — ничего не изменяй и не сбрасывай. Инспектируй реальные файлы, git tracking и тесты; запускай безопасные read-only проверки. Итог по-русски: executive summary, findings по severity с файл:строка, доказательством/сценарием и remediation, результаты команд тестов/coverage, матрица всех пунктов (найдено/проверено/не применимо/не удалось), residual risks. Не раскрывай значения секретов.

---
**Output:**
Write your findings to exactly this path: C:/Users/Пользователь/Desktop/freelance-radar/PROJECT_AUDIT_2026-07-31.md
This path is authoritative for this run.
Ignore any other output filename or output path mentioned elsewhere, including output destinations in the base agent prompt, system prompt, or task instructions.

## Acceptance Contract
Acceptance level: attested
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Return concrete findings with file paths and severity when applicable

Required evidence: review-findings, residual-risks

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