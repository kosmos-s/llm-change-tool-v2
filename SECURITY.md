# Security and data handling

- Original JPG/JSON files are read-only. Work state lives in local `project.db`.
- API keys entered in the app remain in memory. `OPENAI_API_KEY` is an optional environment variable. No key is persisted by the application.
- OpenAI is called only after selecting the provider and acknowledging image transmission in the UI. Mock is the default and never makes network requests.
- The app sends only the selected image pair and versioned prompt to the provider. It does not send the source label or dataset directory.
- SQLite and ZIP backups are **not encrypted**. Store them where only authorized teammates can access them. Reviews may contain project-sensitive descriptions.
- Use a local disk for the DB. UNC paths are blocked; mounted network drives cannot all be detected automatically.
- ZIP imports validate paths, counts, uncompressed size, member SHA256 and dataset/plan/run provenance. Conflicts require an explicit choice.
- Never commit real datasets, screenshots of corporate imagery, keys, DBs, reviewed output, exports or backups. `.gitignore` and `scripts/check_secrets.py` enforce common accidental cases. The scan reads the Git index, so unstaged edits cannot hide a staged secret. setup.bat installs the repository pre-commit hook. Linux developers can run `git config core.hooksPath .githooks`.
- Client-side cost controls use the model prices pinned in the app release. They are estimates, not live pricing or a provider-side billing cap. Verify the displayed checked date and configure provider account/project budgets separately. Timeout/crash outcomes retain a conservative reservation; retry may create an additional billable call.
- No unsigned portable binary is automatically installed or updated. Windows may show a publisher/SmartScreen prompt because this build is not code-signed.
