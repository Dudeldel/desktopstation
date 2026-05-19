# M4 — Jira + Bitbucket integration (Plan)

**Date:** 2026-05-19
**Authored:** Claude (executing /subagent-driven-development per user request)
**Scope:** Real data on screen_1 (Jira) + screen_3 (Dev) + Jira worklog from pomodoro `stop_with_log`.

---

## Working constraints

- **No real credentials available in this session.** Plan builds full scaffolding (HTTP clients, pollers, config + secrets schemas) and verifies via mock HTTP responses (`pytest-httpx` or `respx`). User runs the end-to-end check with their tokens.
- **Field shapes:** Populate the **existing M2-shape Pydantic models** (`Screen1Data` with `today_tasks/queued_tasks/next_meeting`, `Screen3Data` with `prs/standup`). The richer spec shape from `docs/spec/02-serial-protocol.md` is a future refactor — do not change the protocol or firmware layouts in M4.
- **Targets:** Jira Cloud REST API v3, Bitbucket Cloud REST API 2.0.
- **HTTP lib:** `httpx` (already async, fits the daemon's asyncio model). Tests use `respx` for HTTP mocking.

---

## Common context for every task

- Daemon lives at `/home/pc30/Desktop/desktopstation/deskstation-daemon/`.
- Run `cd deskstation-daemon && uv run pytest -q && uv run mypy src/ && uv run ruff check src/ tests/` to verify before reporting DONE.
- The pre-commit hook auto-runs ruff format; if it modifies files, **re-stage and re-commit** rather than amend.
- Commits use Conventional Commits and end with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Branch: `master` (per project convention).
- The daemon never persists secrets in source. `secrets.yaml` at `~/.config/deskstation/secrets.yaml` mode 0600, loaded read-only at startup.

---

## Task M4.1 — Add httpx + respx; secrets/config schema; cache module

**Files:**
- Modify: `deskstation-daemon/pyproject.toml` — add `httpx>=0.27` to `dependencies`, `respx>=0.21` and `pytest-httpx>=0.30` to `dev`.
- Create: `deskstation-daemon/src/deskstation/secrets.py` — Pydantic model + loader for `~/.config/deskstation/secrets.yaml`. Schema (all fields optional):
  ```yaml
  jira:
    base_url: "https://wfirma.atlassian.net"
    email: "..."
    api_token: "..."
  bitbucket:
    workspace: "..."
    email: "..."
    api_token: "..."
  ```
  Loader returns `Secrets(jira: JiraSecrets | None, bitbucket: BitbucketSecrets | None)` — missing file → both None. Permission check: if file exists and isn't 0600, log a warning but still load.
- Modify: `deskstation-daemon/src/deskstation/config.py` — add `JiraPollerConfig` (project_key: str, poll_interval_sec: float = 60.0, enabled: bool = True) and `BitbucketPollerConfig` (workspace, repos: list[str], poll_interval_sec: float = 60.0, enabled: bool = True) to the top-level `Config`.
- Create: `deskstation-daemon/src/deskstation/store/api_cache.py` — SQLite-backed `ApiCache` with `get(key) -> CachedResponse | None`, `put(key, json_bytes, fetched_at)`, `age_sec(key)`. Shared db file at `~/.local/share/deskstation/state/api_cache.sqlite3`. Schema: `(key TEXT PRIMARY KEY, payload BLOB, fetched_at TEXT)`.

**Tests:**
- `tests/test_secrets.py` — missing file, malformed yaml, valid file; per-section None when section absent.
- `tests/test_api_cache.py` — round-trip put/get, age_sec calc, multiple keys, persistence across instances.

**Verification:** `uv run pytest -q` green, mypy + ruff clean.

**Commit:** `feat(daemon): httpx + secrets schema + api cache (M4.1)`

---

## Task M4.2 — Jira API client (REST v3, async, with cache fallback)

**Files:**
- Create: `deskstation-daemon/src/deskstation/clients/__init__.py` (empty).
- Create: `deskstation-daemon/src/deskstation/clients/jira.py` — `JiraClient` class with:
  - `__init__(base_url, email, api_token, cache: ApiCache, http_client: httpx.AsyncClient | None = None)`
  - Auth: HTTP Basic with (email, api_token).
  - Methods (all async, all populate cache on success, fall back to cache on httpx error):
    - `search(jql: str, fields: list[str], max_results: int = 50) -> list[Issue]` — POST `/rest/api/3/search/jql`.
    - `get_sprint(board_id: int) -> SprintInfo | None` — find active sprint via `/rest/agile/1.0/board/{id}/sprint?state=active`.
    - `add_worklog(issue_key: str, seconds: int, started: datetime | None = None) -> bool` — POST `/rest/api/3/issue/{key}/worklog`. No cache fallback (writes can't read from cache).
  - Dataclasses: `Issue(key, summary, status, status_category, assignee_email | None)`, `SprintInfo(id, name, state, start_iso, end_iso)`.
  - On network error: log warning, read cache; if cache miss → raise `JiraTransientError`.

**Tests:** `tests/test_jira_client.py` using `respx`:
- successful search returns parsed Issues
- 500 response → falls back to cache if available
- 500 response + no cache → raises JiraTransientError
- 401 response → raises JiraAuthError (no cache fallback for auth failures)
- add_worklog posts the right body shape (started ISO8601, timeSpentSeconds)
- get_sprint returns None when no active sprint

**Verification + Commit:** `feat(daemon): Jira REST client with cache fallback (M4.2)`

---

## Task M4.3 — Bitbucket API client (Cloud 2.0, async, with cache)

**Files:**
- Create: `deskstation-daemon/src/deskstation/clients/bitbucket.py` — `BitbucketClient`:
  - `__init__(workspace, email, api_token, cache, http_client=None)`
  - Auth: HTTP Basic with (email, api_token).
  - Methods:
    - `list_my_open_prs(username: str) -> list[Pr]` — `/2.0/pullrequests/{username}?state=OPEN`.
    - `list_review_prs(username: str) -> list[Pr]` — search via `/2.0/repositories/{ws}/{repo}/pullrequests?q=reviewers.username="{user}"+AND+state="OPEN"` for each repo in config. Aggregate.
    - `latest_pipeline(repo: str, branch: str = "main") -> PipelineRun | None` — `/2.0/repositories/{ws}/{repo}/pipelines/?sort=-created_on&pagelen=1&target.branch={branch}`.
  - Dataclasses: `Pr(id, title, repo, author_username, source_branch, dest_branch, age_hours, approvals, approvals_required, kind: Literal["mine","review"])`, `PipelineRun(repo, branch, state, started_iso, completed_iso | None)`.
  - Same cache-fallback / transient error pattern as Jira client.

**Tests:** `tests/test_bitbucket_client.py` using respx — analogous to Jira tests.

**Verification + Commit:** `feat(daemon): Bitbucket REST client (M4.3)`

---

## Task M4.4 — Jira poller (replaces Screen1Poller mock)

**Files:**
- Create: `deskstation-daemon/src/deskstation/pollers/jira.py` — `JiraPoller` extending the existing `MockPoller` base pattern. Per tick:
  1. Call `client.search()` for "my open tasks" — JQL: `assignee = currentUser() AND statusCategory != Done AND status in (Draft, "To Do", "In Progress") ORDER BY updated DESC`.
  2. Call `client.search()` for sprint tasks — JQL: `project = "{project_key}" AND sprint in openSprints() ORDER BY status`.
  3. Map each `Issue` → `JiraTask(key, summary, status, is_current=False)`.
  4. `ui_state.set_screen_1(today_tasks=..., queued_tasks=...)` — `today_tasks` from query 1, `queued_tasks` from query 2.
  5. Update an internal `task_summary_index: dict[str, str]` (key → summary) and expose `lookup_summary(key) -> str | None` for the engine.

- Modify: `deskstation-daemon/src/deskstation/engines/pomodoro.py` — accept optional `task_index: Callable[[str], str | None]` in `__init__`; in `start_task(key)` look up summary via this callback and store it. Also accept optional `worklog: Callable[[str, int], Awaitable[bool]]` and call it from `_complete()` when `task_key is not None`.

- Modify: `deskstation-daemon/src/deskstation/main.py` — instantiate `JiraClient` (if `secrets.jira` present and `cfg.jira.enabled`), create `JiraPoller`, pass `poller.lookup_summary` to `PomodoroEngine` as task_index, pass `lambda k, s: client.add_worklog(k, s)` as worklog. If creds missing → log warning, skip poller, keep Screen1Poller mock running.

**Tests:**
- `tests/test_jira_poller.py` — drive poller with a mocked JiraClient (no respx needed; mock the client object). Verify it calls set_screen_1 with the expected JiraTask lists.
- `tests/test_pomodoro_engine.py` (add tests) — engine with task_index callback resolves summary on start_task; engine with worklog callback calls it on completion with elapsed seconds.

**Verification + Commit:** `feat(daemon): Jira poller + engine summary/worklog hooks (M4.4)`

---

## Task M4.5 — Bitbucket poller (replaces Screen3Poller mock)

**Files:**
- Create: `deskstation-daemon/src/deskstation/pollers/bitbucket.py` — `BitbucketPoller`. Per tick:
  1. Call `client.list_my_open_prs(user)` and `client.list_review_prs(user)`. Merge, sort (review first, then mine).
  2. Map to `PullRequest(id, title, author, repo, status, ci)` using the existing M2 model. `status` = "open" for now (Bitbucket doesn't directly expose approved/needs_review without extra calls; mark TODO).
  3. For each repo in config, call `client.latest_pipeline(repo)` and map state→`ci` field on the most recent PR for that repo (best-effort association).
  4. `ui_state.set_screen_3(prs=...)`.

- Modify: `deskstation-daemon/src/deskstation/main.py` — same wire-up pattern as Jira poller.

**Tests:** `tests/test_bitbucket_poller.py` with mocked client.

**Verification + Commit:** `feat(daemon): Bitbucket poller (M4.5)`

---

## Task M4.6 — Disable M2 Screen1/Screen3 mocks when real pollers active; integration smoke test

**Files:**
- Modify: `deskstation-daemon/src/deskstation/pollers/mock.py` — `start_all_mocks` accepts `skip: set[str] = None` so caller can omit "screen_1" / "screen_3" when real pollers are running.
- Modify: `deskstation-daemon/src/deskstation/main.py` — build skip set based on which real pollers were activated; pass to start_all_mocks.
- Create: `tests/test_integration_m4.py` — end-to-end test that wires JiraClient (respx-mocked), JiraPoller, UIState, and a MockBridge; runs one poll tick; asserts a Screen1Msg with the expected JiraTask appears on the bridge.

**Verification + Commit:** `feat(daemon): wire real pollers, disable redundant mocks (M4.6)`

---

## Task M4.7 — README / setup doc update

**Files:**
- Modify: `deskstation-daemon/README.md` — add a section "Configuring real integrations" with the secrets.yaml schema and the four config fields. Include a `chmod 600` instruction and a note that the daemon falls back to mocks when creds are missing.
- Modify: top-level `CLAUDE.md` — append M4 to the milestone list, mention the new pollers and secrets file.

**Verification + Commit:** `docs(daemon): document M4 setup (M4.7)`

---

## Definition of done

- All seven tasks committed and pushed.
- `uv run pytest -q && uv run mypy src/ && uv run ruff check src/ tests/` green on master.
- With `secrets.yaml` populated by user, daemon connects to real Jira + Bitbucket on startup and populates screen_1 + screen_3 with real data; `stop_with_log` on a Jira task produces a worklog entry on the issue.
