"""Runtime artifact contract and safe bootstrap helpers.

Generated files under output/ are intentionally ignored by git.  Render and
fresh local checkouts therefore need a small, explicit contract for which
artifacts may be bootstrapped safely and which artifacts require research
generators before strict validation can pass.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    path: str
    category: str
    source_generator: str
    required_fields: tuple[str, ...]
    safe_bootstrap: bool
    validation: str


RUNTIME_ARTIFACTS: tuple[ArtifactSpec, ...] = (
    ArtifactSpec(
        name="dashboard_artifact",
        path="output/dashboard_artifact.json",
        category="runtime_required",
        source_generator="src.reporting.artifact_generator.generate_dashboard_artifact",
        required_fields=(
            "platform",
            "artifact_schema_version",
            "allocation",
            "strategies",
            "market_monitor",
            "news_risk",
            "recommendations",
            "risk_limits",
            "portfolio_series",
            "data_classification",
            "refresh_status",
        ),
        safe_bootstrap=True,
        validation="Strict deployment validation requires 20 strategies, non-empty literature results, and chart series; runtime bootstrap only requires safe non-live schema fields.",
    ),
    ArtifactSpec(
        name="live_overlay",
        path="output/live_overlay.json",
        category="runtime_optional_cache",
        source_generator="src.market.live_refresh.write_live_overlay",
        required_fields=("data_mode", "market_monitor", "news_risk", "recommendations"),
        safe_bootstrap=True,
        validation="May be rebuilt from the dashboard artifact; missing cache must not block startup.",
    ),
    ArtifactSpec(
        name="intraday_refresh_status",
        path="output/intraday_refresh_status.json",
        category="runtime_status",
        source_generator="src.market.intraday_refresh_service.write_refresh_status",
        required_fields=("state", "in_progress", "last_error"),
        safe_bootstrap=True,
        validation="Status file is operational telemetry only; missing status means no refresh has run yet.",
    ),
)

GENERATED_RESEARCH_ARTIFACTS: tuple[ArtifactSpec, ...] = (
    ArtifactSpec(
        name="strategy_factory_research",
        path="output/research/strategy_factory_v1",
        category="generated_research_fixture",
        source_generator="python scripts/run_rapid_20plus1.py",
        required_fields=("summary.json", "daily_returns.csv"),
        safe_bootstrap=False,
        validation="Generated research evidence; tests must skip or run the generator when absent.",
    ),
    ArtifactSpec(
        name="research_selection_packs",
        path="output/research/*/candidate_summary.csv",
        category="generated_research_fixture",
        source_generator="python scripts/run_final_strategy_research.py and related research scripts",
        required_fields=("candidate_summary.csv", "daily returns CSV", "trade_log.csv", "run_manifest.json"),
        safe_bootstrap=False,
        validation="Generated research evidence; never synthesize market/performance rows for tests.",
    ),
    ArtifactSpec(
        name="shadow_live_outputs",
        path="output/shadow_live",
        category="generated_shadow_fixture",
        source_generator="python scripts/run_shadow_live_daily.py",
        required_fields=("daily_run_manifest.json", "portfolio_daily_ledger.csv", "trade_log.csv"),
        safe_bootstrap=False,
        validation="Generated paper/shadow operational evidence; missing output is an explicit fixture prerequisite.",
    ),
)


def artifact_contract() -> dict[str, Any]:
    return {
        "contract_version": 1,
        "runtime_artifacts": [asdict(spec) for spec in RUNTIME_ARTIFACTS],
        "generated_research_artifacts": [asdict(spec) for spec in GENERATED_RESEARCH_ARTIFACTS],
        "rules": {
            "fresh_deployment": "Runtime must start without ignored output files.",
            "bootstrap_data": "Bootstrap artifacts may use committed canonical operational seed only.",
            "market_data": "Do not fabricate market, performance, brokerage, or live fill data.",
            "strict_validation": "Generated research/paper artifacts must be produced by their source generators before strict evidence tests run.",
            "brokerage": "Live brokerage fills remain disabled and are not represented.",
        },
    }


def write_artifact_contract(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact_contract(), indent=2), encoding="utf-8")


def _load_committed_operational_seed(root: Path) -> dict[str, Any]:
    canonical_path = root / "dashboard" / "data" / "canonical_operational.json"
    if not canonical_path.exists():
        return {}
    return json.loads(canonical_path.read_text(encoding="utf-8"))


def _bootstrap_dashboard_artifact(root: Path, artifact_path: Path) -> dict[str, Any]:
    seed = _load_committed_operational_seed(root)
    portfolio = seed.get("portfolio_summary") or {}
    strategies = seed.get("strategies") or []
    current_weights: dict[str, float] = {}
    artifact_strategies: list[dict[str, Any]] = []
    for strategy in strategies:
        strategy_id = strategy.get("internal_id") or strategy.get("strategy_id") or strategy.get("display_id")
        if not strategy_id:
            continue
        weight = strategy.get("current_weight")
        if weight is not None:
            current_weights[str(strategy_id)] = float(weight)
        artifact_strategies.append(
            {
                "strategy_id": str(strategy_id),
                "name": strategy.get("display_name") or strategy.get("name") or str(strategy_id),
                "current_weight": weight,
                "daily_pnl": strategy.get("daily_pnl"),
                "position_packet": {"latest_positions": []},
            }
        )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    artifact = {
        "platform": "Risk Manager Platform",
        "artifact_schema_version": "refresh_bootstrap_v1",
        "as_of_date": portfolio.get("as_of_date") or seed.get("as_of_date"),
        "initial_capital": portfolio.get("nav") or 1_000_000,
        "allocation": {"current_weights": current_weights, "proposed_weights": current_weights},
        "strategies": artifact_strategies,
        "market_monitor": [],
        "news_risk": {"watch_level": "unavailable", "items": []},
        "recommendations": [],
        "factors": {"portfolio_factor_exposure_current": {}},
        "risk_limits": {"checks": [], "factors": {"checks": []}},
        "portfolio_series": {"dates": [], "returns": [], "cumulative_return": [], "drawdown": []},
        "literature_strategy_backtests": {"results": [], "summary": {}},
        "data_classification": {
            "portfolio_mode": "research_paper_refresh_bootstrap",
            "is_live_portfolio_data": False,
            "market_data_mode": "unavailable_until_refresh",
            "brokerage_execution_enabled": False,
            "live_brokerage_fills_represented": False,
            "disclosure": "Research/paper refresh bootstrap only; no live brokerage fills or fabricated market data.",
        },
        "refresh_status": {
            "state": "bootstrap_artifact_initialized",
            "reason": "output/dashboard_artifact.json was missing",
            "generated_at": now,
            "source": "committed canonical operational dashboard seed",
        },
        "build_metadata": {
            "artifact_generated_at": now,
            "build_id": "refresh-bootstrap",
            "market_as_of": None,
        },
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(artifact, separators=(",", ":")), encoding="utf-8")
    return artifact


def ensure_dashboard_artifact(root: Path, artifact_path: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = artifact_path or root / "output" / "dashboard_artifact.json"
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists():
        artifact = json.loads(resolved.read_text(encoding="utf-8"))
        return artifact, {"state": "existing", "path": str(resolved)}
    artifact = _bootstrap_dashboard_artifact(root, resolved)
    return artifact, {
        "state": "initialized",
        "path": str(resolved),
        "reason": "missing_dashboard_artifact",
    }


def ensure_dashboard_artifact_for_path(path: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_path = Path(path)
    root = artifact_path.parent.parent if artifact_path.parent.name == "output" else Path.cwd()
    return ensure_dashboard_artifact(root, artifact_path)


def validate_runtime_bootstrap_artifact(artifact: dict[str, Any]) -> list[str]:
    missing = []
    required = next(spec for spec in RUNTIME_ARTIFACTS if spec.name == "dashboard_artifact").required_fields
    for field in required:
        if field not in artifact:
            missing.append(field)
    classification = artifact.get("data_classification") or {}
    if classification.get("is_live_portfolio_data") is not False:
        missing.append("data_classification.is_live_portfolio_data=false")
    if classification.get("live_brokerage_fills_represented") is not False:
        missing.append("data_classification.live_brokerage_fills_represented=false")
    return missing
