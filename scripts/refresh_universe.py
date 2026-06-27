"""Refresh universe artifacts from an approved provider source."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.universe.file_provider import DEFAULT_FILE_PROVIDER_INPUT_DIR, FileUniverseProvider
from src.universe.provider_validation import ProviderValidationError
from src.universe.providers import BossApiUniverseProvider, ExistingArtifactUniverseProvider, UniverseDataProvider
from src.universe.universe_builder import DEFAULT_UNIVERSE_OUTPUT_DIR, UniverseBuilder
from src.universe.yfinance_provider import (
    DATA_SOURCE as YFINANCE_DATA_SOURCE,
    NOT_SURVIVOR_BIAS_FREE,
    POINT_IN_TIME_STATUS,
    RESEARCH_USE,
    YFinanceProvisionalUniverseProvider,
)


def build_provider(args: argparse.Namespace, root: Path) -> UniverseDataProvider:
    if args.provider == "file":
        return FileUniverseProvider(root / args.input_dir if not Path(args.input_dir).is_absolute() else args.input_dir)
    if args.provider == "existing-artifacts":
        return ExistingArtifactUniverseProvider(root)
    if args.provider == "boss-api":
        return BossApiUniverseProvider()
    if args.provider == "yfinance-provisional":
        return YFinanceProvisionalUniverseProvider(
            root,
            max_tickers=args.max_tickers,
            universe_names=args.universe,
            use_cache=args.use_cache,
            force_refresh=args.force_refresh,
        )
    raise ValueError(f"unsupported provider: {args.provider}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh Risk Manager universe artifacts.")
    parser.add_argument(
        "--provider",
        choices=("file", "existing-artifacts", "boss-api", "yfinance-provisional"),
        required=True,
        help="Universe provider source.",
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_FILE_PROVIDER_INPUT_DIR),
        help="Input folder for --provider file.",
    )
    parser.add_argument("--as-of-date", default=None, help="Universe as-of date in YYYY-MM-DD format.")
    parser.add_argument(
        "--max-tickers",
        type=int,
        default=None,
        help="Maximum provisional yfinance candidates per applicable tier.",
    )
    parser.add_argument(
        "--universe",
        action="append",
        default=None,
        help="Universe name to refresh; repeat for multiple universes. Default refreshes all configured universes.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore provisional yfinance cache and fetch fresh public data.",
    )
    parser.add_argument(
        "--use-cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use cached provisional yfinance enrichment when available.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_UNIVERSE_OUTPUT_DIR),
        help="Artifact output directory, default data/universe.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    output_path = output_dir if output_dir.is_absolute() else PROJECT_ROOT / output_dir
    provider = build_provider(args, PROJECT_ROOT)
    try:
        result = UniverseBuilder(
            root=PROJECT_ROOT,
            provider=provider,
            output_dir=output_path,
            universe_names=args.universe,
        ).build(as_of_date=args.as_of_date)
    except ProviderValidationError as exc:
        print(f"Universe refresh failed: {exc}", file=sys.stderr)
        return 2
    if args.provider == "yfinance-provisional":
        write_yfinance_coverage_report(PROJECT_ROOT, result.snapshot_payload, result.quality_report)

    print_summary(args.provider, result.snapshot_payload, result.quality_report, result.output_paths)
    return 0


def print_summary(
    provider_name: str,
    snapshot: dict[str, Any],
    quality: dict[str, Any],
    output_paths: dict[str, str | None],
) -> None:
    warnings = sorted(set((snapshot.get("provider") or {}).get("warnings") or []) | set(quality.get("warnings") or []))
    exclusions = Counter(quality.get("excluded_by_reason_total") or {})
    top_exclusions = ", ".join(f"{reason}={count}" for reason, count in exclusions.most_common(5)) or "none"
    provider_metadata = (snapshot.get("provider") or {}).get("metadata") or {}
    field_counts = provider_metadata.get("field_warning_counts") or {}
    ticker_failures = provider_metadata.get("ticker_failures") or []
    print("Universe refresh complete")
    print(f"provider: {provider_name}")
    print(f"source_status: {snapshot.get('source_status')}")
    print(f"as_of_date: {snapshot.get('as_of_date')}")
    print(f"point_in_time_status: {snapshot.get('point_in_time_status')}")
    print(f"research_use: {snapshot.get('research_use', RESEARCH_USE)}")
    print(f"not_survivor_bias_free: {snapshot.get('not_survivor_bias_free', NOT_SURVIVOR_BIAS_FREE)}")
    print("universes:")
    for name, universe in (snapshot.get("universes") or {}).items():
        print(
            "  "
            f"{name}: candidates={universe.get('total_candidates')} "
            f"included={universe.get('included_count')} "
            f"excluded={universe.get('excluded_count')}"
        )
    print(f"top_exclusion_reasons: {top_exclusions}")
    print(f"missing_market_cap_count: {field_counts.get('missing_market_cap', 0)}")
    print(f"missing_sector_count: {field_counts.get('missing_sector', 0)}")
    print(f"yfinance_failures: {len(ticker_failures)}")
    if snapshot.get("data_source") == YFINANCE_DATA_SOURCE:
        print("provisional_warning: This universe is current-membership-only and not survivor-bias-free.")
    print(f"warnings: {len(warnings)}")
    for warning in warnings[:8]:
        print(f"  - {warning}")
    if len(warnings) > 8:
        print(f"  - ... {len(warnings) - 8} more")
    print("artifacts:")
    for label, path in output_paths.items():
        if path:
            print(f"  {label}: {path}")


def write_yfinance_coverage_report(root: Path, snapshot: dict[str, Any], quality: dict[str, Any]) -> None:
    path = root / "docs" / "YFINANCE_PROVISIONAL_UNIVERSE_COVERAGE_REPORT.md"
    provider = snapshot.get("provider") or {}
    metadata = provider.get("metadata") or {}
    lines = [
        "# YFinance Provisional Universe Coverage Report",
        "",
        f"- DATA_SOURCE = {snapshot.get('data_source', YFINANCE_DATA_SOURCE)}",
        f"- POINT_IN_TIME_STATUS = {snapshot.get('point_in_time_status', POINT_IN_TIME_STATUS)}",
        f"- RESEARCH_USE = {snapshot.get('research_use', RESEARCH_USE)}",
        f"- NOT_SURVIVOR_BIAS_FREE = {str(snapshot.get('not_survivor_bias_free', NOT_SURVIVOR_BIAS_FREE)).lower()}",
        "",
        "This universe is current-membership-only and not survivor-bias-free.",
        "",
        "The 5,000-name pool, when available, is for research discovery, AI strategy search, and pipeline testing. It is not the direct optimizer/trading universe.",
        "",
        "## Provider Summary",
        "",
        f"- Status: {snapshot.get('source_status')}",
        f"- As-of date: {snapshot.get('as_of_date')}",
        f"- Version: {snapshot.get('version')}",
        f"- Candidate source counts: `{metadata.get('candidate_sources', {})}`",
        f"- YFinance failures: {len(metadata.get('ticker_failures') or [])}",
        "",
        "## Universe Coverage",
        "",
    ]
    for name, universe in (snapshot.get("universes") or {}).items():
        coverage = universe.get("coverage_summary") or {}
        excluded = Counter(universe.get("excluded_by_reason") or {})
        lines.extend(
            [
                f"### {name}",
                "",
                f"- Total candidates: {universe.get('total_candidates')}",
                f"- Included count: {universe.get('included_count')}",
                f"- Excluded count: {universe.get('excluded_count')}",
                f"- Top exclusion reasons: {dict(excluded.most_common(5))}",
                f"- Price coverage: {_format_coverage(coverage.get('price'))}",
                f"- ADV 20D coverage: {_format_coverage(coverage.get('adv_20d'))}",
                f"- ADV 60D coverage: {_format_coverage(coverage.get('adv_60d'))}",
                f"- Market cap coverage: {_format_coverage(coverage.get('market_cap'))}",
                f"- Sector coverage: {_format_coverage(coverage.get('sector'))}",
                f"- Industry coverage: {_format_coverage(coverage.get('industry'))}",
                f"- Asset type distribution: `{universe.get('asset_type_distribution') or {}}`",
                f"- Exchange distribution: `{universe.get('exchange_distribution') or {}}`",
                f"- Data source: {universe.get('data_source')}",
                f"- Point-in-time status: {universe.get('point_in_time_status')}",
                f"- Warnings: {len(universe.get('data_quality_warnings') or [])}",
                "",
            ]
        )
    lines.extend(
        [
            "## Warnings",
            "",
            *[f"- {warning}" for warning in (quality.get("warnings") or [])[:50]],
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _format_coverage(value: Any) -> str:
    if not isinstance(value, dict):
        return "Unavailable"
    ratio = float(value.get("ratio") or 0.0)
    return f"{value.get('covered', 0)}/{value.get('total', 0)} ({ratio:.1%})"


if __name__ == "__main__":
    raise SystemExit(main())
