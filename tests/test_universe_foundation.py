from __future__ import annotations

import pandas as pd
import pytest

from src.strategies.universe_foundation import (
    diagnostic_small_cap_membership,
    load_point_in_time_membership,
    membership_on_date,
    point_in_time_market_cap,
)


def test_effective_dates_exclude_future_and_remove_exited_security(tmp_path):
    path = tmp_path / "membership.csv"
    pd.DataFrame(
        [
            {"stable_security_id": "1", "ticker": "A", "membership_start": "2020-01-01", "membership_end": "2020-12-31", "source": "wrds", "as_of_date": "2024-01-01"},
            {"stable_security_id": "2", "ticker": "B", "membership_start": "2021-01-01", "membership_end": None, "source": "wrds", "as_of_date": "2024-01-01"},
        ]
    ).to_csv(path, index=False)
    membership = load_point_in_time_membership(path, source_name="WRDS_CRSP")
    assert membership_on_date(membership, "2020-06-01")["ticker"].tolist() == ["A"]
    assert membership_on_date(membership, "2021-06-01")["ticker"].tolist() == ["B"]


def test_current_list_cannot_masquerade_as_point_in_time(tmp_path):
    path = tmp_path / "membership.csv"
    pd.DataFrame(
        [{"stable_security_id": "1", "ticker": "A", "membership_start": "2020-01-01", "membership_end": None, "source": "current_constituent_list", "as_of_date": "2024-01-01"}]
    ).to_csv(path, index=False)
    with pytest.raises(ValueError, match="cannot masquerade"):
        load_point_in_time_membership(path, source_name="CURRENT_LIST")


def test_market_cap_uses_prior_price_and_small_cap_excludes_microcap_tail():
    dates = pd.bdate_range("2024-01-02", periods=2)
    tickers = list("ABCDEFGHIJ")
    shares = pd.DataFrame(1.0, index=dates, columns=tickers)
    close = pd.DataFrame([range(1, 11), range(2, 12)], index=dates, columns=tickers)
    cap = point_in_time_market_cap(shares, close)
    assert cap.loc[dates[1], "A"] == 1
    broad = pd.DataFrame(
        [{"rebalance_date": dates[1], "ticker": ticker, "included": True, "reason": "included"} for ticker in tickers]
    )
    first = diagnostic_small_cap_membership(broad, cap)
    second = diagnostic_small_cap_membership(broad, cap)
    pd.testing.assert_frame_equal(first, second)
    selected = first.loc[first["included"], "ticker"].tolist()
    assert "A" not in selected
    assert selected == ["B", "C", "D"]
