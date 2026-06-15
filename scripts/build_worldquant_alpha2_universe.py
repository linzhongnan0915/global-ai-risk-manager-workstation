"""Build the WorldQuant Alpha #2 US-listed security master and candidate universe."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.strategies.worldquant.universe import (
    DEFAULT_CANDIDATES_OUTPUT,
    DEFAULT_MASTER_OUTPUT,
    build_universe_from_download,
    format_audit_summary,
    write_universe_outputs,
)
from src.strategies.worldquant.research_universe import (
    DEFAULT_RESEARCH_UNIVERSE_V1_OUTPUT,
    build_research_universe_v1_audit,
    filter_research_universe_v1,
    format_research_universe_v1_audit,
    write_research_universe_v1,
)
from src.strategies.worldquant.pilot_universe import (
    DEFAULT_PILOT_UNIVERSE_OUTPUT,
    build_pilot_universe_audit,
    format_pilot_universe_audit,
    select_pilot_universe,
    write_pilot_universe,
)


def main() -> None:
    master, candidates, summary = build_universe_from_download()
    master_path, candidates_path = write_universe_outputs(
        master,
        candidates,
        master_path=DEFAULT_MASTER_OUTPUT,
        candidates_path=DEFAULT_CANDIDATES_OUTPUT,
    )
    research_universe = filter_research_universe_v1(master)
    research_summary = build_research_universe_v1_audit(master, candidates)
    research_path = write_research_universe_v1(
        research_universe,
        output_path=DEFAULT_RESEARCH_UNIVERSE_V1_OUTPUT,
    )
    print(format_audit_summary(summary))
    print(f"Wrote security master: {master_path}")
    print(f"Wrote common-stock candidates: {candidates_path}")
    print()
    print(format_research_universe_v1_audit(research_summary))
    print(f"Wrote research universe v1: {research_path}")

    pilot_universe = select_pilot_universe(research_universe)
    pilot_summary = build_pilot_universe_audit(research_universe, pilot_universe)
    pilot_path = write_pilot_universe(pilot_universe, output_path=DEFAULT_PILOT_UNIVERSE_OUTPUT)
    print()
    print(format_pilot_universe_audit(pilot_summary))
    print(f"Wrote pilot universe: {pilot_path}")


if __name__ == "__main__":
    main()
