from __future__ import annotations

import pandas as pd

from src.universe.point_in_time import POINT_IN_TIME_STATUS, filter_point_in_time_members, get_universe_members


def test_point_in_time_membership_excludes_future_and_expired_members():
    membership = pd.DataFrame(
        [
            {
                "universe_name": "TEST",
                "security_id": "A",
                "ticker": "A",
                "membership_start_date": "2020-01-01",
                "membership_end_date": "2021-01-01",
                "source": "test",
                "version": "v1",
            },
            {
                "universe_name": "TEST",
                "security_id": "B",
                "ticker": "B",
                "membership_start_date": "2021-01-01",
                "membership_end_date": None,
                "source": "test",
                "version": "v1",
            },
            {
                "universe_name": "TEST",
                "security_id": "C",
                "ticker": "C",
                "membership_start_date": "2022-01-01",
                "membership_end_date": None,
                "source": "test",
                "version": "v1",
            },
        ]
    )
    assert filter_point_in_time_members(membership, "TEST", "2020-06-01")["ticker"].tolist() == ["A"]
    assert filter_point_in_time_members(membership, "TEST", "2021-06-01")["ticker"].tolist() == ["B"]
    assert filter_point_in_time_members(membership, "TEST", "2019-12-31").empty


def test_get_universe_members_marks_current_membership_only_provisional(tmp_path):
    path = tmp_path / "membership.csv"
    pd.DataFrame(
        [
            {
                "universe_name": "US_LARGE_CAP_CORE",
                "security_id": "A",
                "ticker": "A",
                "membership_start_date": "2026-06-22",
                "membership_end_date": None,
                "as_of_date": "2026-06-22",
                "source": "current_artifact",
                "version": "v1",
                "inclusion_reason": "included",
                "exclusion_reason": None,
            }
        ]
    ).to_csv(path, index=False)

    past = get_universe_members("US_LARGE_CAP_CORE", "2026-06-21", membership_path=path)
    current = get_universe_members("US_LARGE_CAP_CORE", "2026-06-22", membership_path=path)

    assert past["members"] == []
    assert current["members"] == ["A"]
    assert current["point_in_time_status"] == POINT_IN_TIME_STATUS
    assert "not survivor-bias-free" in current["warnings"][0]
