# Providers

AgentsFlow reads issues via pluggable providers registered with the workflow activities. Provider selection is automatic unless you explicitly set `provider` on `IssueRequest`.

## Routing rules
- The registry prefers providers in reverse registration order (Jira, then GitHub) that both support the URL and are configured.
- If a matching provider is discovered but not configured, the workflow raises a clear error so you can supply credentials.
- Passing `provider="jira"` or `provider="github"` in the workflow input forces that backend and skips auto-detection.

## Jira
- **URLs matched:** hosts containing `atlassian.net` or `jira`, plus any domain in `JIRA_HOST_ALLOWLIST` (e.g., `issues.company.com`).
- **Auth:** `JIRA_EMAIL` and `JIRA_API_TOKEN` are required. Requests fail fast when either is missing.
- **Optional settings:**
  - `JIRA_HOST_ALLOWLIST` – comma-separated hostnames to treat as Jira.
  - `JIRA_TIMEOUT_SECONDS` – per-request timeout override (default 15s).
- **Data returned:** `issue_key`, `summary`, `description`, `status`, and normalized comments (author, body, created/updated timestamps).

## GitHub
- **URLs matched:** `https://github.com/<owner>/<repo>/issues/<number>`.
- **Auth:** `GITHUB_TOKEN` is recommended for higher rate limits; anonymous reads work but are throttled and may not see private issues.
- **Optional settings:**
  - `GITHUB_TIMEOUT_SECONDS` – per-request timeout override (default 15s).
- **Data returned:** `owner/repo#<number>` key, title, body, state, and comment list (author, timestamps, body).

## Troubleshooting
- *"not configured" errors* indicate the URL matched a provider whose credentials are missing—export the required env vars.
- *"Unable to determine an issue provider"* means no provider supports the URL; confirm the URL format or set `provider` explicitly.
- Ensure the worker host can reach the issue tracker over the network; timeouts respect the `*_TIMEOUT_SECONDS` overrides above.
