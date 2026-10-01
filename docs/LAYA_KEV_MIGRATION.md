# Laya + AIMAN-Kev migration

## Decision

AIMAN now treats **Laya as the generic System-One runtime** and **Kev as AIMAN domain specialization and historical decision data**.

The control boundary does not change:

```text
TaskEnvelope
  -> Laya System-One (shadow / advisory)
  -> AIMAN decision snapshot
  -> deterministic Agent Router
  -> human gate for side effects
  -> AgentDock
```

A model decision is never authorization.

## Phase 1: shadow migration

This branch adds two question profiles:

- **Router shadow**: worker, risk level, confirmation need, web need, world-model need.
- **Kev compatibility**: the existing robotics decisions (content/event/timeline/source judgments) expressed with Laya `choice`, `score`, and `noul` primitives.

All Laya answers are observational in Phase 1. They do not affect route hints or execution. For robotics tasks, the existing AIMAN-Kev v0.2c path remains the temporary compatibility hint source while Laya is evaluated side-by-side. Those existing hints still pass through the deterministic capability registry.

## Runtime

Laya runs on the Mac inside an isolated Python 3.12 environment and is exposed
only on loopback. The Router does **not** connect to that HTTP service directly.

```text
Router on AgentDock VPS
  -> AIMAN_DECISION_MCP (SSH stdio)
  -> Mac Decision MCP systemone_analyze
  -> http://127.0.0.1:8014/v1/systemone
  -> Laya
```

The Mac Decision MCP remains the security boundary. No public listener and no
Tailscale-facing Laya HTTP port are required. The local runtime is configured
to use cached model artifacts offline after initial installation.

The persistent service lifecycle is intentionally separate from Router code.
If the remote worknode session cannot register a user LaunchAgent, the service
must be started by an already-authorized Mac service manager or interactive
user session; the Router must not escalate privileges to achieve persistence.

## Kev assets that remain valuable

Do not discard historical Kev material. Convert it into:

1. labelled Laya fine-tuning rows,
2. calibration/evaluation sets,
3. hard negatives and disagreement cases,
4. regression fixtures for robotics decisions,
5. AgentDock routing/outcome traces.

The IWM Sensor-Kev and Decision Packet contracts remain unchanged in Phase 1 so existing contribution workflows keep working.

## Promotion rule

The Router shadow profile must not gain execution authority merely because its accuracy improves. Promotion requires separate evidence for:

- task/worker accuracy,
- Brier score / calibration error,
- option-order stability,
- OOD/abstention behavior,
- false-negative rate on high-risk actions,
- latency on the target local hardware.

Side effects remain policy-gated even after promotion.
