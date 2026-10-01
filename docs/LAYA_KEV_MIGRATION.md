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

Only the legacy-compatible route hints are eligible to affect the existing read-only route, and they still pass through the deterministic capability registry. The generic Router answers are recorded only for comparison and training-data collection.

## Runtime

Run upstream Laya's native HTTP server:

```bash
python -m pip install "laya[serve]"
LAYA_PRELOAD=1 laya-serve
```

AgentDock bridge configuration:

```bash
export AIMAN_LAYA_URL=http://127.0.0.1:8000/v1/systemone
# Optional:
export AIMAN_LAYA_API_KEY=...
export AIMAN_LAYA_MODEL=multilingual
```

For a Mac-hosted model, point `AIMAN_LAYA_URL` at the allowlisted/Tailscale-reachable service rather than exposing it publicly.

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
