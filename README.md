# AIMAN Agent Router

AIMAN 的任务路由与能力编排层。

核心边界：World Model 负责状态，Kev 提供判断提示，Router 负责路由与规划，AgentDock 负责执行。v0.1 采用 deterministic-first、fail-closed，并要求所有 side-effect 进入人审门。

See `docs/architecture.md` for the full design.
