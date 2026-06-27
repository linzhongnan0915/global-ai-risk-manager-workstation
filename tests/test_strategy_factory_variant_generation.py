from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.strategies.strategy_factory_data import ensure_data_layout, write_inventory_and_quality
from src.strategies.strategy_factory_readiness import write_material_generation_artifacts
from src.strategies.strategy_factory_variants import REQUIRED_VARIANT_FIELDS, generate_strategy_variants


def _write_proxy_inventory(data_root: Path, symbols: tuple[str, ...] = ("CPER", "DBC", "UUP", "COPX", "XME", "SPY")) -> None:
    ensure_data_layout(data_root)
    dates = pd.bdate_range("2024-01-02", periods=20)
    rows = []
    for symbol in symbols:
        for idx, date in enumerate(dates):
            rows.append(
                {
                    "date": date.date().isoformat(),
                    "symbol": symbol,
                    "open": 20 + idx,
                    "high": 20.5 + idx,
                    "low": 19.5 + idx,
                    "close": 20 + idx,
                    "adj_close": 20 + idx,
                    "volume": 1000,
                }
            )
    prices = pd.DataFrame(rows)
    prices.to_csv(data_root / "prices" / "daily_ohlcv.csv", index=False)
    write_inventory_and_quality(data_root, prices, "TEST_FIXTURE", [])


def _write_gate2_run(root: Path, run_id: str = "SF_RUN_VARIANT_FIXTURE") -> Path:
    run_dir = root / "output" / "strategy_factory" / "runs" / run_id
    run_dir.mkdir(parents=True)
    material_id = "MAT_CONTROLLED_COPPER_FIXTURE"
    manifest = {
        "run_id": run_id,
        "selected_material_ids": [material_id],
        "selected_material_names": ["controlled_copper_strategy_material.md"],
        "generated_artifacts": {
            "current_run_candidate": str(run_dir / "current_run_candidate.json"),
            "test_spec": str(run_dir / "test_spec.md"),
        },
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "selected_materials.json").write_text(
        json.dumps([{"material_id": material_id, "filename": "controlled_copper_strategy_material.md"}], indent=2),
        encoding="utf-8",
    )
    (run_dir / "current_run_candidate.json").write_text(json.dumps({"strategy_id": "CURRENT_RUN_COPPER_FIXTURE"}, indent=2), encoding="utf-8")
    (run_dir / "test_spec.md").write_text("Copper commodity trend proxy using CPER, DBC, UUP and volatility filters.", encoding="utf-8")
    (run_dir / "data_availability.json").write_text(
        json.dumps(
            {
                "decision": "PROXY_ONLY",
                "available_symbols": ["CPER", "DBC", "UUP", "COPX", "XME", "SPY"],
                "usable_symbols": ["CPER", "COPX", "XME"],
                "benchmark_symbol": "DBC",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "proxy_mapping_used.json").write_text(
        json.dumps({"mapping": {"copper": ["CPER", "JJC", "DBB", "COPX"], "usd_proxy": ["UUP"], "equity_benchmark": ["SPY"]}}, indent=2),
        encoding="utf-8",
    )
    (run_dir / "strategy_type_classification.json").write_text(
        json.dumps({"status": "COMPLETED", "strategy_type": "commodity trend / macro proxy"}, indent=2),
        encoding="utf-8",
    )
    (run_dir / "feature_plan.json").write_text(json.dumps({"status": "COMPLETED", "included_features": ["momentum_63d"]}, indent=2), encoding="utf-8")
    (run_dir / "evidence_report.md").write_text("# Evidence\n", encoding="utf-8")
    (run_dir / "intelligence_report.md").write_text("# Intelligence\n", encoding="utf-8")
    return run_dir


def _write_theme_run(root: Path, run_id: str, text: str, filename: str) -> Path:
    run_dir = root / "output" / "strategy_factory" / "runs" / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "selected_material_ids": [f"MAT_{run_id}"],
        "selected_material_names": [filename],
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "selected_materials.json").write_text(
        json.dumps([{"material_id": f"MAT_{run_id}", "filename": filename, "text": text}], indent=2),
        encoding="utf-8",
    )
    lower = text.lower()
    theme = (
        "etf_momentum_rotation"
        if "etf" in lower
        else "us_stock_low_vol_defensive"
        if any(token in lower for token in ("low vol", "low-vol", "low volatility", "lower volatility", "defensive", "realized volatility"))
        else "us_stock_cross_sectional_momentum_quality"
        if "u.s. stock" in lower or "u.s. equity" in lower
        else "unknown_review_required"
    )
    (run_dir / "data_requirements.json").write_text(
        json.dumps(
            {
                "theme": theme,
                "benchmark_symbol": "SPY" if "ETF" in text else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "data_availability.json").write_text(json.dumps({"decision": "PROXY_ONLY", "available_symbols": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]}, indent=2), encoding="utf-8")
    (run_dir / "proxy_mapping_used.json").write_text(json.dumps({"mapping": {"etf_rotation": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]}}, indent=2), encoding="utf-8")
    (run_dir / "strategy_type_classification.json").write_text(json.dumps({"status": "COMPLETED"}, indent=2), encoding="utf-8")
    (run_dir / "feature_plan.json").write_text(json.dumps({"status": "COMPLETED"}, indent=2), encoding="utf-8")
    return run_dir


def test_gate2_variant_generation_creates_distinct_specs_without_evaluation_artifacts(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_proxy_inventory(data_root)
    run_dir = _write_gate2_run(workstation_root)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    registry = generate_strategy_variants(workstation_root, "SF_RUN_VARIANT_FIXTURE")

    variants_dir = run_dir / "variants"
    registry_path = variants_dir / "variant_registry.json"
    assert registry_path.is_file()
    assert registry["variant_count"] >= 3
    assert len(registry["variants"]) == registry["variant_count"]

    specs = []
    for row in registry["variants"]:
        spec_path = Path(row["variant_spec_path"])
        assert spec_path.is_file()
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        specs.append(spec)
        for field in REQUIRED_VARIANT_FIELDS:
            assert field in spec, field
        assert spec["candidate_status"] == "NOT_CANDIDATE_GATE2"

    signal_formulas = {spec["signal_formula"] for spec in specs}
    assert len(signal_formulas) >= 3
    assert any(spec["testability_status"] in {"READY_TO_TEST", "PROXY_ONLY"} for spec in specs)

    forbidden_names = [
        "backtest_run.json",
        "metrics.json",
        "ml_diagnostics_run.json",
        "ranking.json",
        "ranked_variants.json",
    ]
    generated_names = {path.name for path in variants_dir.rglob("*") if path.is_file()}
    assert not set(forbidden_names).intersection(generated_names)
    assert (variants_dir / "variant_generation_report.md").is_file()


def test_gate2_etf_material_generates_etf_variants_without_copper_leakage(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_proxy_inventory(data_root, ("SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"))
    run_dir = _write_theme_run(
        workstation_root,
        "SF_RUN_ETF_FIXTURE",
        "ETF Momentum Rotation: rank SPY QQQ IWM EFA EEM TLT GLD by 63d plus 126d momentum monthly and hold top 2 or top 3.",
        "etf_momentum_rotation_material.md",
    )
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    registry = generate_strategy_variants(workstation_root, "SF_RUN_ETF_FIXTURE")

    assert registry["theme"] == "etf_momentum_rotation"
    assert registry["variant_count"] == 2
    specs_text = ""
    for row in registry["variants"]:
        assert row["theme"] == "etf_momentum_rotation"
        spec = json.loads(Path(row["variant_spec_path"]).read_text(encoding="utf-8"))
        specs_text += json.dumps(spec)
        assert spec["strategy_name"].startswith("ETF Momentum Rotation")
        assert spec["benchmark"] == "SPY"
        assert spec["universe_or_proxy"] == ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]
        assert "63d" in spec["signal_formula"]
        assert "126d" in spec["signal_formula"]
    assert "COPX" not in specs_text
    assert "XME" not in specs_text
    assert "Copper Equity Proxy Trend" not in specs_text
    assert "copper" not in specs_text.lower()
    assert (run_dir / "variants" / "variant_generation_report.md").is_file()


def test_gate2_unknown_material_generates_review_required_only(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    _write_proxy_inventory(data_root, ("SPY",))
    _write_theme_run(workstation_root, "SF_RUN_UNKNOWN_FIXTURE", "A vague research note without a tradable universe.", "unknown_note.md")
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    registry = generate_strategy_variants(workstation_root, "SF_RUN_UNKNOWN_FIXTURE")
    spec = json.loads(Path(registry["variants"][0]["variant_spec_path"]).read_text(encoding="utf-8"))

    assert registry["theme"] == "unknown_review_required"
    assert registry["variant_count"] == 1
    assert spec["variant_id"] == "REVIEW_REQUIRED_UNKNOWN_MATERIAL_V1"
    assert spec["testability_status"] == "REVIEW_REQUIRED"
    assert "copper" not in json.dumps(spec).lower()


def test_gate2_us_stock_material_generates_stock_variants_without_copper_or_etf_universe(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    stock_symbols = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "JPM", "XOM", "UNH", "AVGO", "SPY")
    _write_proxy_inventory(data_root, stock_symbols)
    _write_theme_run(
        workstation_root,
        "SF_RUN_US_STOCK_FIXTURE",
        "U.S. stock cross-sectional momentum quality screen over a U.S. equity universe with benchmark SPY.",
        "us_stock_momentum_quality_material.md",
    )
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    registry = generate_strategy_variants(workstation_root, "SF_RUN_US_STOCK_FIXTURE")
    specs_text = ""
    variant_ids = {row["variant_id"] for row in registry["variants"]}

    assert registry["theme"] == "us_stock_cross_sectional_momentum_quality"
    assert {
        "US_STOCK_MOMENTUM_12_1_TOP50_V1",
        "US_STOCK_MOMENTUM_6_1_TOP50_V1",
        "US_STOCK_MOMENTUM_QUALITY_TOP50_V1",
        "US_STOCK_MOMENTUM_LIQUIDITY_FILTER_TOP50_V1",
    }.issubset(variant_ids)
    for row in registry["variants"]:
        spec = json.loads(Path(row["variant_spec_path"]).read_text(encoding="utf-8"))
        specs_text += json.dumps(spec)
        assert spec["theme"] == "us_stock_cross_sectional_momentum_quality"
        assert spec["benchmark"] == "SPY"
        assert spec["strategy_name"].startswith("U.S. Stock")
        assert spec["universe_or_proxy"] != ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"]
        assert "AAPL" in spec["universe_or_proxy"]
        assert "quality" in json.dumps(spec).lower()
    assert "COPX" not in specs_text
    assert "XME" not in specs_text
    assert "copper" not in specs_text.lower()
    assert "ETF Momentum Rotation" not in specs_text


def test_gate2_us_stock_low_vol_material_generates_defensive_variants_only(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    stock_symbols = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "JPM", "XOM", "UNH", "AVGO", "SPY")
    _write_proxy_inventory(data_root, stock_symbols)
    _write_theme_run(
        workstation_root,
        "SF_RUN_US_LOW_VOL_FIXTURE",
        "U.S. stock low volatility defensive screen over a U.S. equity universe with benchmark SPY, ranking by 63d and 126d realized volatility.",
        "us_stock_low_vol_defensive_material.md",
    )
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))

    registry = generate_strategy_variants(workstation_root, "SF_RUN_US_LOW_VOL_FIXTURE")
    specs_text = ""
    variant_ids = {row["variant_id"] for row in registry["variants"]}

    assert registry["theme"] == "us_stock_low_vol_defensive"
    assert {
        "US_STOCK_LOW_VOL_63D_TOP20_V1",
        "US_STOCK_LOW_VOL_126D_TOP20_V1",
        "US_STOCK_LOW_VOL_BETA_FILTER_TOP20_V1",
    }.issubset(variant_ids)
    assert not any(variant_id.startswith("US_STOCK_MOMENTUM") for variant_id in variant_ids)
    assert not any(variant_id.startswith("ETF_ROTATION") for variant_id in variant_ids)
    for row in registry["variants"]:
        spec = json.loads(Path(row["variant_spec_path"]).read_text(encoding="utf-8"))
        specs_text += json.dumps(spec)
        assert spec["theme"] == "us_stock_low_vol_defensive"
        assert spec["benchmark"] == "SPY"
        assert "Low Vol Defensive" in spec["strategy_name"]
        assert "realized volatility" in spec["signal_formula"].lower()
    assert "COPX" not in specs_text
    assert "XME" not in specs_text
    assert "Copper Equity Proxy Trend" not in specs_text
    assert "ETF Momentum Rotation" not in specs_text
    assert "Momentum + Quality" not in specs_text


def test_material_hashes_produce_distinct_strategy_names_and_variant_ids(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    stock_symbols = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "JPM", "XOM", "UNH", "AVGO", "SPY")
    _write_proxy_inventory(data_root, stock_symbols)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))
    momentum_path = Path("strategy_factory/intake_queue/examples/us_stock_momentum_quality_material.md").resolve()
    low_vol_path = Path("strategy_factory/intake_queue/examples/us_stock_low_vol_defensive_material.md").resolve()

    momentum = write_material_generation_artifacts(workstation_root, momentum_path, run_id="SF_RUN_HASH_MOMENTUM")
    low_vol = write_material_generation_artifacts(workstation_root, low_vol_path, run_id="SF_RUN_HASH_LOW_VOL")
    momentum_registry = generate_strategy_variants(workstation_root, momentum["run_id"])
    low_vol_registry = generate_strategy_variants(workstation_root, low_vol["run_id"])

    assert momentum["spec"]["source_material_hash"] != low_vol["spec"]["source_material_hash"]
    assert momentum["spec"]["strategy_name"] != low_vol["spec"]["strategy_name"]
    assert momentum_registry["theme"] == "us_stock_cross_sectional_momentum_quality"
    assert low_vol_registry["theme"] == "us_stock_low_vol_defensive"
    assert {row["variant_id"] for row in momentum_registry["variants"]}.isdisjoint({row["variant_id"] for row in low_vol_registry["variants"]})


def test_phase3c_us_stock_material_produces_generated_research_artifacts_and_variants(tmp_path: Path, monkeypatch) -> None:
    workstation_root = tmp_path / "workstation"
    data_root = tmp_path / "market_data"
    symbols = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOG", "JPM", "XOM", "UNH", "AVGO", "SPY")
    _write_proxy_inventory(data_root, symbols)
    monkeypatch.setenv("STRATEGY_FACTORY_DATA_ROOT", str(data_root))
    material_path = Path("strategy_factory/intake_queue/examples/us_stock_momentum_quality_material.md").resolve()

    generated = write_material_generation_artifacts(workstation_root, material_path, run_id="SF_RUN_PHASE3C_US_STOCK_TEST")
    registry = generate_strategy_variants(workstation_root, generated["run_id"])
    run_dir = workstation_root / "output" / "strategy_factory" / "runs" / generated["run_id"]
    metadata = json.loads((run_dir / "material_metadata.json").read_text(encoding="utf-8"))
    research_card = json.loads((run_dir / "research_card.json").read_text(encoding="utf-8"))
    readiness = json.loads((run_dir / "readiness_status.json").read_text(encoding="utf-8"))

    assert metadata["generated_from_material"] is True
    assert metadata["source_material_path"] == str(material_path)
    assert metadata["source_material_hash"]
    assert metadata["theme"] == "us_stock_cross_sectional_momentum_quality"
    assert research_card["strategy_name"] == "U.S. Stock Momentum + Quality Screen"
    assert (run_dir / "test_spec.md").is_file()
    assert (run_dir / "evidence_manifest.json").is_file()
    assert readiness["automation_ready"] is False
    assert readiness["automation_block_reason"] == "EVIDENCE_NOT_RUN"
    assert registry["variant_count"] == 4
    assert all(row["theme"] == "us_stock_cross_sectional_momentum_quality" for row in registry["variants"])
    spec_text = (run_dir / "variants" / "US_STOCK_MOMENTUM_12_1_TOP50_V1" / "variant_spec.json").read_text(encoding="utf-8")
    assert "COPX" not in spec_text and "XME" not in spec_text
    assert "Copper Equity Proxy Trend" not in spec_text
    assert "source_material_hash" in spec_text


def test_phase3c_unknown_material_is_not_automation_ready(tmp_path: Path) -> None:
    material_path = tmp_path / "unknown_material.md"
    material_path.write_text("# Note\n\nThis is an unclassified research memo without a tradable universe.", encoding="utf-8")

    generated = write_material_generation_artifacts(tmp_path / "workstation", material_path, run_id="SF_RUN_PHASE3C_UNKNOWN_TEST")
    readiness = generated["readiness"]

    assert generated["spec"]["theme"] == "unknown_review_required"
    assert readiness["automation_ready"] is False
    assert readiness["automation_block_reason"] == "UNKNOWN_MATERIAL"
