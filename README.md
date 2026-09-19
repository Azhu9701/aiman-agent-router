# AIMAN Agent Router

AIMAN 的任务路由、能力编排与可追溯执行控制层。

## Boundary

- **World Model** owns domain state and evidence.
- **AIMAN-Kev** provides compact decision signals and route hints.
- **Agent Router** owns deterministic capability selection and execution planning.
- **AgentDock** owns environment-specific execution across VPS, Mac worknodes, APIs, tools, and physical nodes.

The Router never gets authority to bypass canonical-world-model review rules.

## v0.2 live path

```text
Task input
  -> AIMAN-Kev v0.2c
  -> route hints
  -> Capability Registry
  -> deterministic RoutingDecision
  -> ExecutionPlan
  -> AgentDock bridge
  -> Robotics IWM read
  -> verification
  -> immutable trace
```

The live runtime is **read-only**. Side-effecting tasks still stop at a human gate.

### DeepSeek Harness proposal worker

`aiman.deepseek-harness-headless` is a proposal-only local coding worker. The Router can select it for `code_analysis`, `patch_proposal`, `repo_debugging`, and `test_execution`. AgentDock forwards the task to the restricted Mac Work Node, which exports the registered workspace's committed `HEAD` into an ephemeral Git repository with **no remotes**, runs the fixed DeepSeek Harness `headless` profile there, and returns the final response, Git patch, changed-file names, and source/version/latency metadata.

The source workspace is not modified by this worker. Applying a returned patch remains a separate bounded Work Node write/review step.

```bash
python -m aiman_agent_router live examples/live-deepseek-proposal.json
```

### Run a static route

```bash
python -m aiman_agent_router route examples/robotics-event-research.json
```

### Run a live trace on an AgentDock node

The environment supplies an allowlisted JSON bridge through
`AIMAN_ROUTER_BRIDGE` (default:
`/srv/agentdock/.local/bin/aiman-router-bridge`). The source-controlled
reference implementation is `aiman_agent_router.agentdock_bridge`; a node
wrapper can execute that module while keeping credentials and host config in
the runtime environment.

```bash
python -m aiman_agent_router live examples/live-viabot.json
```

The first live reference path connects:

- `kev.analyze` -> AIMAN-Kev v0.2c decision packet
- `iwm.timeline.search` -> 聚身之家 verified Event Store
- `agentdock.health` -> execution-fabric health snapshot
- `deepseek.harness.propose` -> isolated Mac DeepSeek Harness proposal worker

Each run persists a trace containing the original input, Kev provenance,
TaskEnvelope, RoutingDecision, ExecutionPlan, execution rows, verification
result, and a SHA-256 trace hash.

### Replay routing

```bash
python -m aiman_agent_router replay /path/to/trace.json
```

Replay does not repeat external actions; it recomputes the deterministic route
against the current registry so routing drift is visible.

## Safety invariants

1. deterministic routing before model-driven routing
2. fail closed on unmapped capabilities
3. environment credentials remain outside this repository
4. live v0.2 execution is read-only
5. canonical World Model writes still require Contribution -> PR -> CI -> Review
6. DeepSeek Harness proposals run in an ephemeral no-remote Git snapshot; source-workspace writes are separate
7. traces are persisted and hash-checked

See `docs/architecture.md` for the full architecture.
