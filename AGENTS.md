# AIMAN Agent Router: Agent entry point

This repository owns deterministic capability selection, execution planning, and immutable trace records. It sits between task input and an allowlisted execution fabric; the World Model owns canonical domain facts and AgentDock owns environment-specific actions.

## What an Agent may do

- Read the schemas, registry descriptors, and examples before constructing a task.
- Route a task deterministically, fail closed on unmapped capabilities, and replay a trace to expose routing drift.
- Run the read-only live path and inspect verification and trace output.
- Propose a bounded patch through the proposal worker; applying that patch is a separate reviewed action.

## What an Agent must not do

- Write canonical World Model data, bypass Contribution -> PR -> CI -> Review, or treat a route decision as authorization.
- Invent capabilities, registry entries, credentials, evidence, or environment state.
- Turn natural language into an arbitrary shell command or add a side effect to the read-only live path.

## Contract and validation

The JSON files under `schemas/`, descriptors under `registry/`, and examples under `examples/` are the machine-readable contract. Preserve their existing protocol versions and public semantics. A task is complete when the smallest relevant route or schema change is covered by the existing tests and its boundary is explicit.

Run the repository checks from its root:

    python3 -m compileall -q src tests
    python3 -m unittest discover -s tests -v

Read the relevant schema and test before changing a route. Unknown mappings fail closed. For the decision loop that precedes a route change, use the lightweight `reality-first-development` protocol; this repository remains the routing and trace contract.
