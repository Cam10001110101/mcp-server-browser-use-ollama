# Security remediation and verification

Reviewed on November 11, 2026 (America/Chicago), from commit
`bb2df962f0bf6a21e9ff3b92c26f85db96d7f53d`.

This records a source review, dependency audit and tested remediation. It is not a
completed hosted Codex Security scan or a guarantee that every vulnerability has
been found.

## Scope and trust boundaries

Reviewed both application modules, their callers and tests, packaging, MCP
configuration, documentation and all GitHub Actions workflows. The server accepts
requests over local stdio and controls isolated browser contexts. Browser pages,
extraction patterns and model output can contain attacker-controlled data. Assets
include page contents, browser resource availability and the host account's
privileges. The local MCP client and operator-selected server script are trusted.

There is no HTTP MCP listener or multi-user authentication boundary in this
repository. Localhost/private-network browsing is intentional and remains
supported. Predictable session IDs are not treated as a cross-user vulnerability
in this local, single-client design.

## Remediations

| Issue | Evidence and change | Verification |
| --- | --- | --- |
| Extraction pattern became executable JavaScript | A quoted pattern set a harmless global marker when the original generated code was evaluated. `extract_data_impl` now passes patterns through Playwright's argument serializer, never through JavaScript source interpolation. SVG class handling also preserves ordinary extraction on mixed HTML/SVG pages. | Actual sandboxed Chromium tests cover marker and throwing payloads, backslashes/newlines, quoted ordinary text and predefined price extraction. |
| Chromium sandbox disabled | Launch explicitly passed `--no-sandbox`; Playwright also defaults `chromium_sandbox` to false. Launch now explicitly enables it, with no unsafe fallback. | Assert launch configuration and run the real browser regression with sandboxing enabled. A browser exploit was not demonstrated; this restores a missing containment control. |
| Concurrent launches bypassed the session cap | Eleven overlapping launches passed a ten-session cap because only completed sessions counted. Pending launches now reserve capacity synchronously before the first await. | A blocked launch consumes the final slot; a concurrent launch is rejected before starting Playwright. |
| Failed/cancelled startup and cleanup leaked resources | Navigation failure/cancellation left all acquired resources open. One close failure skipped every later close. Cleanup now attempts each acquired resource independently, shields against MCP/AnyIO cancellation and bounds each close. Stdio shutdown cleans registered sessions. | Failures and cancellation across driver startup/launch/context/page/viewport/navigation, real AnyIO cancellation, close errors and stdio shutdown. |
| Screenshot failure left temporary files | Temporary files used `delete=False` and unlink only ran on success. Screenshots now stay in memory. | Success and failure paths pass no output path to Playwright; real capture succeeds. |

The extraction issue executes in the browser page's origin, not directly in the
host shell. Exploitability requires control over the extraction tool's input,
including potentially through an influenced model. Resource exhaustion likewise
requires access to the local MCP request stream. No unauthenticated remote server
exploit is claimed.

## Dependencies and compatibility

The starting installed environment had three distinct advisories in three packages
(the audit service returned the certifi advisory twice):

| Package | Before | Locked after | Advisory |
| --- | --- | --- | --- |
| Black | 26.5.1 | 26.10.1 | CVE-2026-114134 / GHSA-cg8m-r9f2-5wm2 |
| certifi | 2026.7.22 | 2026.10.23 | PYSEC-2026-4320 / GHSA-6q48-6c7w-9gw2 |
| opentelemetry-api | 1.45.0 | 1.45.2 | CVE-2026-114603 / GHSA-xcq7-p3pf-p88h |

Black's advisory concerns its separate GitHub Action, which this repository does
not use. No inbound OpenTelemetry HTTP instrumentation was found in this stdio
application. Their upgrades are dependency hygiene; installation alone does not
prove these two advisories were exploitable here. certifi's affected trust store
is relevant to Python HTTP clients.

Runtime and development packages were upgraded and resolved into `uv.lock`,
including MCP 2.3.0, Playwright 1.65.1, langchain-core 1.8.0 and
langchain-ollama 1.1.0. Security floors also protect non-lockfile installations of
the known affected packages. Python **3.11+** is now required by the current
LangChain release; CI covers 3.11–3.14. MCP 2 uses constructor callbacks and
snake-case Python model fields; the MCP wire tool names and schemas are preserved.
Console entry points now run their async main functions and the enhanced-client
alias points to the consolidated client. Python subprocesses use the active
interpreter so they load the tested environment.

The final PyPI advisory audit examined **96 locked third-party package versions**,
including development/build packages and dependencies selected only on other
platforms. It found **zero known vulnerabilities**, with no exclusions or skipped
packages. The editable application itself is covered by source review, not the
package advisory database. The machine-readable result is
[`security-dependency-audit.json`](security-dependency-audit.json).

Install and refresh Chromium after upgrading Playwright; updating its Python wheel
alone does not replace an already-installed browser:

```bash
uv sync --locked --extra dev
uv run --locked playwright install chromium
```

To repeat the complete lockfile advisory check without executing dependency builds:

```bash
mkdir -p /tmp/browser-dependency-audit
uv export --locked --extra dev --no-emit-project --format pylock.toml \
  --output-file /tmp/browser-dependency-audit/pylock.toml
uv run --locked pip-audit --locked /tmp/browser-dependency-audit --strict
```

The PEP 751 export allows pip-audit to inspect all locked package versions rather
than only packages selected by the auditing machine's environment markers.

## CI and supply chain

Actions are pinned to verified upstream release commit SHAs. The test workflow
uses a pinned setup-uv action and uv version instead of a downloaded shell script,
read-only repository permissions and non-persistent checkout credentials. Test
failures are no longer ignored. Weekly and pull-request dependency audits cover
the whole lockfile, and Dependabot monitors Python and GitHub Actions updates.
Claude automation uses its current stable action, gates triggers to trusted
repository associations, and skips automatic review of fork PRs. This is defense
in depth, not a claim that the previous action allowed a demonstrated secret leak.

## Verification

- Baseline: 29 passed, 17 failed. Failures referenced the previously removed
  FastMCP API. Those tests now exercise the current implementation without adding
  obsolete production aliases or hiding failures.
- Unit/integration: 71 passed (`uv run --locked pytest -m 'not e2e'`). This includes
  launching the server as a real stdio subprocess and checking MCP initialization,
  tool listing, schema rejection, tool errors and shutdown.
- Browser: one E2E test passed with system Chromium 151.0.7922.173, sandbox enabled,
  a disposable local HTTP page and no external websites. CI uses the browser
  bundled with the locked Playwright release. Ubuntu's AppArmor restrictions
  require a user-namespace permission scoped to that executable; CI installs that
  profile while retaining Chromium sandboxing and system-wide restrictions.
  GitHub's first run passed the Python tests on Linux, macOS and Windows; its
  browser test exposed the missing AppArmor profile, which is addressed here.
- `uv pip check`, critical Ruff checks, source/wheel build, console entry-point
  smoke checks, GitHub Actions validation with actionlint, and `git diff --check`
  passed.
- The fix-finding workflow included an independent read-only boundary investigation
  and a separate read-only candidate review. The reviewer found a driver-startup
  cancellation leak in the first candidate. After fixing it, an actual Playwright
  initialization cancellation reproduction confirmed the Node driver exited with
  code 0 and no pending or active session remained; two regression tests cover
  AnyIO and direct asyncio cancellation. The reviewer did not rerun the revision.

## Remaining limits and operating guidance

- Codex Security access was confirmed. The required desktop scan-start/progress/
  completion tools were unavailable in this session, so no canonical hosted scan
  was started or completed. Cloud discovery found no environment containing this
  repository. The cloud workflow exposed `gpt-5.6-sol`, not a selectable Daybreak
  model. No Daybreak model execution is claimed; scan token usage is unavailable.
- Advisory results reflect the queried PyPI database at review time. They do not
  cover future disclosures, OS packages, browser internals, Ollama itself, or
  third-party Actions' transitive runtime downloads. Keep the host, browser and
  Ollama patched. GitHub alert inventories could not be queried with the available
  connector endpoints, and CLI reads returned `Forbidden`; no alerts were dismissed.
- Arbitrary webpages and model output remain untrusted. The automated client can
  take actions based on page contents; prompt injection is not solved by this
  patch. Use a dedicated unprivileged environment without sensitive sessions,
  external network restrictions for untrusted tasks, and supervision for sensitive
  or irreversible actions. Do not expose the stdio server as an unauthenticated
  remote service.
- Browser cleanup is bounded and best-effort if the operating system or browser
  process is unresponsive. Force-killing the server bypasses Python cleanup.
- The main branch was unprotected when inspected. Requiring the test and security
  jobs before merging would prevent bypassing these checks; repository protection
  settings were not changed.
