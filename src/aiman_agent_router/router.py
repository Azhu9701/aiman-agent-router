from __future__ import annotations

from collections.abc import Iterable

from .models import (
    CapabilityDescriptor,
    ExecutionPlan,
    ExecutionStep,
    RoutingDecision,
    TaskEnvelope,
)
from .registry import CapabilityRegistry


class AgentRouter:
    """Fail-closed deterministic routing core.

    Kev/LLM adapters may propose domains and capabilities, but this class owns
    the final registry-based selection. Missing capabilities never get guessed.
    """

    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    @staticmethod
    def _domain_match(task: TaskEnvelope, descriptor: CapabilityDescriptor) -> bool:
        return "*" in descriptor.domains or bool(set(task.domains) & set(descriptor.domains))

    @staticmethod
    def _score(task: TaskEnvelope, descriptor: CapabilityDescriptor) -> int:
        if not descriptor.enabled:
            return -10_000
        domain_matches = len(set(task.domains) & set(descriptor.domains))
        wildcard = "*" in descriptor.domains
        capability_matches = len(set(task.required_capabilities) & set(descriptor.capabilities))
        score = descriptor.priority
        score += domain_matches * 40
        score += 10 if wildcard else 0
        score += capability_matches * 30
        if task.evidence_required and descriptor.provenance in {"required", "supported"}:
            score += 15
        if task.freshness_required and descriptor.freshness:
            score += 10
        return score

    def _rank_candidates(self, task: TaskEnvelope) -> list[tuple[CapabilityDescriptor, int]]:
        ranked: list[tuple[CapabilityDescriptor, int]] = []
        for descriptor in self.registry.all():
            if not descriptor.enabled or descriptor.type == "execution_fabric":
                continue
            if not self._domain_match(task, descriptor):
                continue
            overlap = set(task.required_capabilities) & set(descriptor.capabilities)
            if task.required_capabilities and not overlap:
                continue
            ranked.append((descriptor, self._score(task, descriptor)))
        ranked.sort(key=lambda item: (-item[1], -item[0].priority, item[0].id))
        return ranked

    def route(self, task: TaskEnvelope) -> RoutingDecision:
        required = set(task.required_capabilities)
        uncovered = set(required)
        ranked = self._rank_candidates(task)
        selected: list[CapabilityDescriptor] = []

        if required:
            for descriptor, _score in ranked:
                covered = uncovered & set(descriptor.capabilities)
                if not covered:
                    continue
                selected.append(descriptor)
                uncovered -= covered
                if not uncovered:
                    break

        candidate_scores = {descriptor.id: score for descriptor, score in ranked}
        missing = tuple(sorted(uncovered))
        human_review = task.side_effects or bool(missing)
        status = "ready" if not missing and bool(selected) else "needs_review"

        reasons: list[str] = []
        if selected:
            reasons.append(
                "selected descriptors cover required capabilities using deterministic registry matching"
            )
        if missing:
            reasons.append("fail-closed: one or more required capabilities have no eligible descriptor")
        if task.side_effects:
            reasons.append("side-effecting tasks require a human review gate in v0.1")
        if not required:
            reasons.append("fail-closed: required_capabilities must be supplied by intake/Kev before execution")
            human_review = True
            status = "needs_review"

        return RoutingDecision(
            task_id=task.task_id,
            status=status,
            selected=tuple(item.id for item in selected),
            candidate_scores=candidate_scores,
            missing_capabilities=missing,
            human_review_required=human_review,
            reasons=tuple(reasons),
        )

    def plan(self, task: TaskEnvelope, decision: RoutingDecision) -> ExecutionPlan:
        steps: list[ExecutionStep] = []
        prior: list[str] = []

        for index, identifier in enumerate(decision.selected, start=1):
            descriptor = self.registry.get(identifier)
            overlap = tuple(sorted(set(task.required_capabilities) & set(descriptor.capabilities)))
            step_id = f"capability_{index}"
            kind = {
                "world_model": "query_world_model",
                "agent": "invoke_agent",
                "decision_model": "invoke_decision_model",
            }.get(descriptor.type, "invoke_capability")
            steps.append(
                ExecutionStep(
                    id=step_id,
                    kind=kind,
                    target=descriptor.id,
                    capabilities=overlap,
                    depends_on=tuple(prior),
                    metadata={
                        "protocols": list(descriptor.protocols),
                        "provenance": descriptor.provenance,
                    },
                )
            )
            prior.append(step_id)

        executor = self._select_executor()
        if steps and executor is not None:
            steps.append(
                ExecutionStep(
                    id="execute",
                    kind="execution_fabric",
                    target=executor.id,
                    capabilities=("execute_plan",),
                    depends_on=tuple(prior),
                    metadata={"protocols": list(executor.protocols)},
                )
            )
            prior = ["execute"]

        steps.append(
            ExecutionStep(
                id="verify",
                kind="verify_result",
                target="aiman.router.verifier",
                capabilities=("evidence_check", "policy_check"),
                depends_on=tuple(prior),
                metadata={
                    "evidence_required": task.evidence_required,
                    "freshness_required": task.freshness_required,
                },
            )
        )
        prior = ["verify"]

        if decision.human_review_required:
            steps.append(
                ExecutionStep(
                    id="human_review",
                    kind="human_gate",
                    target="aiman.review",
                    depends_on=tuple(prior),
                    metadata={"reason": "side_effect_or_unresolved_capability"},
                )
            )

        return ExecutionPlan(
            task_id=task.task_id,
            status=decision.status,
            steps=tuple(steps),
            human_review_required=decision.human_review_required,
        )

    def _select_executor(self) -> CapabilityDescriptor | None:
        executors: Iterable[CapabilityDescriptor] = self.registry.by_type("execution_fabric")
        eligible = [
            item for item in executors
            if "execute_plan" in item.capabilities
        ]
        if not eligible:
            return None
        eligible.sort(key=lambda item: (-item.priority, item.id))
        return eligible[0]

    def route_and_plan(self, payload: dict) -> dict:
        task = TaskEnvelope.from_dict(payload)
        decision = self.route(task)
        plan = self.plan(task, decision)
        return {
            "task": task.to_dict(),
            "decision": decision.to_dict(),
            "plan": plan.to_dict(),
        }
