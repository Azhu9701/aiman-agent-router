# Multi-agent development coordination (stage 1)

Status: **library + tests only**. This is not deployed, not wired to
NexusDock task_manage, and not a production deployment capability.

## One source of truth per concern

- NexusDock `task_manage`: task goals, progress, checkpoint and final review.
- AIMAN Agent Node: trusted node/worker inventory, workspace policy, SSH/Tailscale
  admission, credentials kept outside Git.
- AIMAN Agent Router: deterministic routing and this optional **central**
  development-lease primitive (temporary assignment/conflict state only).
- Mac Studio: preferred application-development and verification node.
- GitHub: committed code, PRs, CI, review, and the final merge boundary.
- Production: **never** a development worker or automatic fallback.

An AgentDock **node** is different from a worknode/SSH execution **worker**.
Do not count an SSH alias as an independently registered NexusDock node.

## Prevent overlapping edits

A central scheduler first resolves a valid active NexusDock task, canonical
Git repository, registered workspace, target branch and impacted areas. It must
verify worker admission from administrator-maintained inventory; the worker
cannot submit its own capabilities or allowlist.

Then the scheduler atomically calls `DevelopmentLeaseStore.claim()` using a
SQLite DB located on **one** coordinator host (never copied between workers).
The lease controls an entire task, its Git branch, and explicitly named areas.
Area keys are **exact match**; choose stable, conservative module scopes
(e.g. `backend/parts`, `frontend/parts`) and let shared migrations/config
have their own single-owner scopes.

The claim returns a private token and monotonically increasing epoch. Only
the assigned worker receives them over an authenticated channel. Neither goes
into PR descriptions, traces, dashboards, ticket comments, CI logs, or Git.

- A second worker cannot claim an active task, branch or identical area.
- Non-overlapping scopes and branches may proceed concurrently.
- Workers renew before the lease expires and must stop editing immediately if
  renewal fails. A coordinator can reclaim expired ownership.
- Release requires both the correct token and epoch. A stale worker cannot
  renew or release a newer claim.
- `active()` exposes sanitized status, never a token.

**A lease is not authorization to edit, push, merge, access secrets, or deploy.**
Existing workspace permissions and all GitHub branch policies still apply.
Leases do not physically stop processes that ignore expiry; PR/CI/review and
short-lived development credentials remain essential defense-in-depth.

## Approved development flow

1. Create or resume a central NexusDock task with acceptance criteria.
2. Analyze code impact using current Mac CodeGraph (or normal Git source
   inspection when the repo is not indexed/unavailable).
3. Read the current `AGENTS.md` inheritance and inspect `git status`.
4. Obtain one coordinator lease for explicit areas and a uniquely named
   `agent/<task>-<topic>` branch at a captured base SHA.
5. Create an isolated Git worktree for that assignment. Never share a
   writable worktree between agents; never reset unrelated dirty changes.
6. Run relevant registered checks, produce a PR, attach test evidence and
   check the base SHA and affected files.
7. Have an independent reviewer check behavior, security and integration.
8. Merge through protected GitHub rules; deploy only through the separately
   authorized release channel. End the task through NexusDock final_review.
9. Release the lease and clean only the task's confirmed disposable worktree.

## Worker enrollment

`examples/development-workers.json` is a **non-live example only**. The
central scheduler must pass `load_trusted_workers()` a trusted local copy of
the admin-managed AIMAN Agent Node worker registry, not user-controlled task
JSON. Missing or disabled development workers cannot acquire a lease. The
example deliberately leaves the future server disabled; neither the server's
identity nor its security posture has been verified.

Before adding a Grokbot or any other node: verify its host identity, SSH/Tailscale
path, non-admin Unix identity, GitHub credentials with minimum repo scopes,
allowed workspaces, no production secrets, health checks, and actual command
capabilities. Register the AgentDock **node** with NexusDock separately if it
will run AgentDock, then grant only explicit development workspaces. Validate
a read-only task before enabling patch submission.

## Python API (coordinator only)

```python
from aiman_agent_router.development_leases import (
    DevelopmentLeaseStore,
    load_trusted_workers,
)

store = DevelopmentLeaseStore(
    "/private/central-state/development-leases.sqlite",
    allowed_workers=load_trusted_workers("/private/verified-workers.json"),
)
claim = store.claim(
    task_id="tsk_123", worker_id="mac-worknode", workspace="aiman-agent-router",
    repository="Azhu9701/aiman-agent-router",
    branch="agent/tsk-123-coordination", base_sha="a" * 40,
    resources=["router-core"],
)
# Store claim["token"] securely; do not log it. Renew with epoch + token.
store.release(task_id=claim["task_id"], epoch=claim["epoch"],
              token=claim["token"])
```

This API is not currently a remote service or CLI. A scheduler using it must
add authenticated transport, trusted Nexus task status checks, recoverable
delivery of the lease token, heartbeats, and monitoring before any real
multi-server enforcement can be claimed.

## Stage-1 acceptance

- Atomic contention tests: exactly one winner for the same resource.
- Fail-closed: unknown/disabled workers, main branch, bad scope or missing
  scope cannot be claimed.
- Expiry + fencing: stale token/epoch cannot renew a newer assignment.
- Dashboard status never exposes secrets.
- Router's existing read-only `live` and `serve` paths stay unchanged.
- No production database, API, service, deploy or GitHub branch rule changed.

Future work: wire verified central task IDs and node registry to a single
coordinator service on a private network, expose read-only state to the
management dashboard, configure GitHub branch protection/required checks,
then enroll and test a second independent node end-to-end.
