from __future__ import annotations

from typing import Any


ROUTER_SHADOW_QUESTIONS: dict[str, dict[str, Any]] = {
    "worker": {
        "type": "choice",
        "instructions": "Which AIMAN execution target best fits this task?",
        "criteria": {
            "mac-worknode": "Local development, repository work, local files, or compute on the user's Mac work node.",
            "production": "Read-only inspection or explicitly gated operations against production services.",
            "vps": "Control-plane, orchestration, public API, or network-facing work that belongs on the AgentDock VPS.",
            "none": "No execution worker should be selected from the available targets.",
        },
    },
    "risk_level": {
        "type": "score",
        "instructions": "Rate the operational risk if this task were executed.",
        "criteria": [
            "read-only or no external side effect",
            "low-risk reversible side effect",
            "meaningful write requiring explicit confirmation",
            "high-impact production, destructive, financial, or physical action",
        ],
    },
    "needs_confirmation": {
        "type": "noul",
        "instructions": "Should a human explicitly confirm before any side effect is executed?",
    },
    "needs_web": {
        "type": "noul",
        "instructions": "Does completing this task require fresh public web information?",
    },
    "needs_world_model": {
        "type": "noul",
        "instructions": "Does this task require consulting an AIMAN industry world model?",
    },
}


KEV_COMPAT_QUESTIONS: dict[str, dict[str, Any]] = {
    "content_type": {
        "type": "choice",
        "instructions": "Classify the robotics-industry content into the closest decision category.",
        "criteria": {
            "event": "A dated real-world industry event or announcement.",
            "company_profile": "Primarily describes a company rather than a discrete event.",
            "robot_product": "Primarily describes a robot product, specification, or capability.",
            "project_or_dataset": "Primarily describes an open-source project, model, dataset, or technical artifact.",
            "roundup_or_digest": "A multi-item roundup, digest, or aggregation rather than one event.",
            "other": "None of the listed categories fit reliably.",
        },
    },
    "is_event": {
        "type": "noul",
        "instructions": "Is the source mainly about a discrete real-world event that can be placed on a timeline?",
    },
    "event_type": {
        "type": "choice",
        "instructions": "If this is a robotics-industry event, choose the closest canonical event type.",
        "criteria": {
            "product_announcement": "A product is announced but not necessarily released.",
            "product_release": "A product becomes publicly released or available.",
            "mass_production": "A product enters mass production.",
            "deployment": "A robot or system is deployed into real operations.",
            "funding": "A financing, investment, or fundraising event.",
            "partnership": "A partnership, cooperation agreement, or joint initiative.",
            "acquisition": "An acquisition or merger event.",
            "open_source_release": "A model, dataset, project, or technical artifact is released as open source.",
            "facility_opening": "A factory, laboratory, or other facility opens or begins operation.",
            "other": "The item appears to be an event but does not fit the canonical event types.",
        },
    },
    "timeline_worthy": {
        "type": "noul",
        "instructions": "Is this event significant and concrete enough to enter the canonical robotics timeline?",
    },
    "commercialization_stage": {
        "type": "choice",
        "instructions": "Choose the closest commercialization stage described by the source.",
        "criteria": {
            "research": "Research or pre-product work without a demonstrated prototype.",
            "prototype": "Prototype or demo stage.",
            "pilot": "Pilot, trial, proof-of-concept, or limited customer testing.",
            "commercial_deployment": "Commercial deployment or real customer operation.",
            "mass_production": "Scaled manufacturing or mass-production stage.",
            "not_applicable": "Commercialization stage is not applicable to the item.",
            "unclear": "The source does not support a reliable stage judgment.",
        },
    },
    "source_quality": {
        "type": "score",
        "instructions": "Rate the evidence quality of the supplied source set.",
        "criteria": [
            "weak, unverifiable, anonymous, or low-quality sourcing",
            "secondary reporting with limited direct evidence",
            "reputable secondary reporting or corroborated industry reporting",
            "direct primary, official, regulatory, academic, or equivalent first-party evidence",
        ],
    },
    "needs_second_source": {
        "type": "noul",
        "instructions": "Should AIMAN require another independent source before treating the item as verified?",
    },
}


def uses_kev_compat_profile(payload: dict[str, Any]) -> bool:
    domains = payload.get("domains")
    metadata = payload.get("metadata")
    return (
        isinstance(domains, list)
        and "robotics" in domains
    ) or (
        isinstance(metadata, dict)
        and isinstance(metadata.get("kev_input"), dict)
    )


def build_laya_request(
    payload: dict[str, Any],
    task_id: str,
    *,
    include_kev: bool,
) -> dict[str, Any]:
    metadata = payload.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    kev_input = metadata.get("kev_input")
    kev_input = kev_input if isinstance(kev_input, dict) else {}

    state = {
        "task_id": task_id,
        "goal": str(payload.get("goal") or ""),
        "domains": payload.get("domains") if isinstance(payload.get("domains"), list) else [],
        "intent": str(payload.get("intent") or ""),
        "required_capabilities": (
            payload.get("required_capabilities")
            if isinstance(payload.get("required_capabilities"), list)
            else []
        ),
        "constraints": payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {},
        "evidence_required": bool(payload.get("evidence_required", True)),
        "freshness_required": bool(payload.get("freshness_required", False)),
        "side_effects": bool(payload.get("side_effects", False)),
    }
    if include_kev:
        state["robotics_content"] = {
            "content_id": str(kev_input.get("content_id") or task_id),
            "title": str(kev_input.get("title") or payload.get("goal") or ""),
            "summary": str(kev_input.get("summary") or ""),
            "content": str(kev_input.get("content") or payload.get("goal") or ""),
            "source_types": (
                kev_input.get("source_types")
                if isinstance(kev_input.get("source_types"), list)
                else []
            ),
            "source_count": (
                kev_input.get("source_count")
                if isinstance(kev_input.get("source_count"), int)
                else None
            ),
        }

    questions = dict(ROUTER_SHADOW_QUESTIONS)
    if include_kev:
        questions.update(KEV_COMPAT_QUESTIONS)

    return {
        "state": state,
        "questions": questions,
        # AIMAN serves bilingual tasks and pre-caches this checkpoint on the
        # Mac. Pinning it avoids offline auto-routing to an uncached model.
        "model": "multilingual",
    }


def _answer_payload(answer: dict[str, Any]) -> dict[str, Any]:
    kind = str(answer.get("type") or "")
    if kind == "choice":
        value = answer.get("choice")
    elif kind == "score":
        value = answer.get("score")
    elif kind == "noul":
        value = answer.get("noul")
    else:
        value = None
    return {
        "type": kind,
        "answer": value,
        "confidence": answer.get("confidence"),
        "probabilities": answer.get("probabilities"),
        "low_confidence": bool(answer.get("low_confidence", False)),
    }


def normalize_laya_result(
    result: dict[str, Any],
    *,
    include_kev: bool,
) -> dict[str, Any]:
    answers = result.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("Laya result is missing answers")

    normalized_answers = {
        name: _answer_payload(answer)
        for name, answer in answers.items()
        if isinstance(answer, dict)
    }

    # Phase 1 is observation-only. In particular, do not infer boolean
    # semantics from a raw noul scalar until the AIMAN-specific contract is
    # calibrated against Future Gold.
    route_hints: list[str] = []

    upstream_provenance = result.get("provenance")
    upstream_provenance = (
        upstream_provenance if isinstance(upstream_provenance, dict) else {}
    )
    routing = result.get("routing")
    if not isinstance(routing, dict):
        routing = upstream_provenance.get("routing")
    routing = routing if isinstance(routing, dict) else {}
    usage = result.get("usage")
    usage = usage if isinstance(usage, dict) else {}

    return {
        "provider": "laya",
        "mode": "shadow",
        "production_effect": "none",
        "decisions": normalized_answers,
        "router_shadow": {
            name: normalized_answers.get(name)
            for name in ROUTER_SHADOW_QUESTIONS
            if name in normalized_answers
        },
        "kev_compat": {
            name: normalized_answers.get(name)
            for name in KEV_COMPAT_QUESTIONS
            if name in normalized_answers
        } if include_kev else {},
        "route_hints": {
            "required_capabilities": route_hints,
        },
        "provenance": {
            "engine": "laya",
            "model": (
                upstream_provenance.get("model")
                or routing.get("model")
                or result.get("model")
            ),
            "routing": routing,
            "transport": result.get("transport"),
            "endpoint": result.get("endpoint"),
            "usage": usage,
        },
    }
