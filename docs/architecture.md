# AIMAN Agent Router Architecture

## Purpose

AIMAN Agent Router decides **where a task should go, which capabilities should be composed, and what execution gate is required**.

It is intentionally separate from:

- **Industry World Model (IWM):** canonical domain state and contribution protocol.
- **AIMAN-Kev:** lightweight classification, route hints, evidence/risk judgments.
- **AgentDock:** execution fabric across VPS, Mac worknodes, APIs, MCP/A2A endpoints, browsers, and eventually robots/factories.
- **emibot / Production Sensor:** domain sensing and verified event production.

## Control plane

```text
User / Agent / API
        |
        v
    TaskEnvelope
        |
        v
  Intake / Kev hint
        |
        v
Capability Registry
        |
        v
Deterministic Router
        |
        v
  ExecutionPlan
        |
        v
     AgentDock
        |
        v
Verifier / Human Gate
        |
        v
   Result / Action
```

## v0.1 invariants

1. **Deterministic before generative.** LLMs and Kev may propose route hints; the registry owns final eligibility.
2. **Fail closed.** Missing capability mapping returns `needs_review`; the router never invents a target.
3. **World models own state.** The router does not copy canonical industry data into its own database.
4. **AgentDock owns execution.** The router emits plans; execution occurs in the execution fabric.
5. **No canonical bypass.** World-model writes remain Contribution -> PR -> CI -> Review -> Canonical.
6. **Side effects are gated.** In v0.1 every side-effecting task requires human review.
7. **Every decision is traceable.** Task, routing decision, execution plan, evidence, model/tool versions and final result should form one trace.

## Core objects

- `TaskEnvelope`
- `CapabilityDescriptor`
- `RoutingDecision`
- `ExecutionPlan`
- `ExecutionResult`

These objects are AIMAN-owned protocol objects. MCP, A2A, model SDKs and vendor APIs are adapters around them rather than the router's internal contract.

## Registry model

The registry starts as version-controlled JSON. A descriptor declares:

- identity and type
- domains
- capabilities
- protocols
- provenance support
- freshness
- write policy
- execution target
- priority and enabled state

The initial registry contains:

- `aiman.robotics` — 聚身之家 Robotics Industry World Model
- `aiman.public-web-research` — public evidence gathering
- `aiman.kev` — decision-model adapter boundary
- `aiman.agentdock` — execution fabric

## Routing algorithm

v0.1 performs a deterministic greedy capability cover:

1. Filter disabled descriptors.
2. Filter by task domain.
3. Keep descriptors that cover at least one required capability.
4. Score domain specificity, capability overlap, evidence support, freshness and configured priority.
5. Select descriptors until all required capabilities are covered.
6. If any capability remains uncovered, return `needs_review`.
7. Build an ordered execution plan and append verification.
8. Append a human gate for side effects or unresolved capability coverage.

This deliberately avoids an unconstrained "LLM chooses any tool" architecture.

## v0.2 live runtime

v0.2 adds an environment-neutral JSON bridge. The Router invokes only
allowlisted operations and does not know SSH credentials, private hostnames, or
MCP transport details.

```text
LiveRouterRuntime
  -> agentdock.health
  -> kev.analyze
  -> merge route hints into TaskEnvelope
  -> deterministic route + plan
  -> iwm.timeline.search
  -> verifier
  -> TraceStore
```

The initial live runtime is deliberately read-only. A Kev event classification
can add `event_query`; `needs_second_source=true` can add
`evidence_gathering`. The registry still decides whether those capabilities
have an eligible target.

A trace records input, Kev model/contract provenance, deterministic decision,
plan, execution-fabric snapshot, live outputs, verification, and a canonical
SHA-256 hash. `replay` recomputes the deterministic route without repeating
external actions.

Environment-specific implementation belongs to AgentDock. The reference bridge
supports only `agentdock.health`, `kev.analyze`, and
`iwm.timeline.search`; any other operation fails closed.

## Next milestones

### v0.3
- MCP and A2A adapters.
- cost/latency-aware routing.
- multi-world-model task graph.
- dynamic Task World Model composition.
- replay/evaluation suite from real AIMAN traces.
