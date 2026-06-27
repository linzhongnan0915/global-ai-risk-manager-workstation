"""Run a controlled Strategy Factory selected-batch smoke test.

This script uses the same local backend plugin path that the dashboard calls:
save upload material, run selected batch, then inspect generated artifacts and
dashboard payload fields. It does not run or fabricate backtest/ML results.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALPHA_ROOT = Path("D:/Global_Ai/alpha_research")
DEFAULT_OUT_DIR = ROOT / "output" / "strategy_factory_functionality_audit"
CONTROLLED_CONTENT = """# Controlled Copper Strategy Smoke Material

Copper price forecasting strategy using 3-month momentum, volatility filter,
USD trend, and inventory signal.
Universe: copper ETF/proxy.
Benchmark: broad commodities or SPY.
Rebalance monthly.
No leverage.

Research hypothesis: copper/commodities trend persistence may be improved by
filtering exposure when realized volatility is elevated, USD trend is adverse,
or inventory conditions deteriorate.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alpha-root", default=str(DEFAULT_ALPHA_ROOT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    os.environ["STRATEGY_FACTORY_ALPHA_RESEARCH_ROOT"] = args.alpha_root
    sys.path.insert(0, str(ROOT))

    from src.strategies.strategy_factory_plugin import (  # noqa: PLC0415
        UploadedMaterial,
        base_state,
        run_factory,
        save_uploaded_materials,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    material_path = out_dir / "controlled_copper_strategy_material.md"
    material_path.write_text(CONTROLLED_CONTENT, encoding="utf-8")

    upload = save_uploaded_materials(
        ROOT,
        [UploadedMaterial(filename=material_path.name, content=material_path.read_bytes())],
    )
    material = upload["saved"][0]
    run = run_factory(ROOT, selected_material_ids=[material["material_id"]])
    payload = base_state(ROOT)
    generated = run.get("run_manifest", {}).get("generated_artifacts", {}) or {}
    paths = {
        "controlled_material": str(material_path),
        "stored_material": material.get("stored_path"),
        "extracted_text": material.get("extracted_text_path"),
        "selected_materials_json": generated.get("selected_materials"),
        "material_summary_json": generated.get("material_summary"),
        "extracted_ideas_json": generated.get("extracted_ideas"),
        "research_card": (generated.get("research_cards") or [None])[0],
        "test_spec": (generated.get("test_specs") or [None])[0],
        "current_run_candidate": generated.get("current_run_candidate"),
        "current_run_report": generated.get("current_run_report"),
        "run_manifest": run.get("run", {}).get("run_manifest_path"),
        "batch_manifest": run.get("run", {}).get("batch_manifest_path"),
        "run_log": generated.get("run_log"),
    }
    text_blob_parts: list[str] = []
    for value in paths.values():
        if value and Path(value).is_file():
            text_blob_parts.append(Path(value).read_text(encoding="utf-8", errors="replace")[:12000])
    text_blob = "\n".join(text_blob_parts).lower()
    result = {
        "material": material,
        "run": run.get("run"),
        "run_manifest": run.get("run_manifest"),
        "batch_manifest": run.get("batch_manifest"),
        "candidate": run.get("candidate"),
        "dashboard_payload_subset": {
            "latest_run": payload.get("latest_run"),
            "latest_run_output": payload.get("latest_run_output"),
            "current_run_candidates_count": len(payload.get("current_run_candidates") or []),
            "first_current_run_candidate": (payload.get("current_run_candidates") or [{}])[0],
        },
        "paths": paths,
        "path_exists": {key: bool(value and Path(value).is_file()) for key, value in paths.items()},
        "keyword_hits": {
            word: word in text_blob
            for word in ["copper", "commodit", "momentum", "volatility", "benchmark", "rebalance"]
        },
        "backtest_status": "NOT_IMPLEMENTED / BLOCKED",
        "ml_status": "NOT_IMPLEMENTED / BLOCKED",
    }
    out_path = out_dir / "smoke_result_after_fix.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
