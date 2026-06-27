# Universe Point-In-Time Policy

## Purpose

Universe membership must be timestamped before it is used for alpha research, ML features, backtests, portfolio simulation, or strategy-specific eligibility checks.

## Membership Rule

For any `signal_date`, strategy research may only use securities where:

```text
membership_start_date <= signal_date
and
(membership_end_date is null or signal_date < membership_end_date)
```

This prevents future entrants from being used in past simulations and removes expired members after their membership window ends.

## Current Release Status

True historical index and broad-market membership are not yet available in this release. Current artifacts must therefore be labeled:

```text
POINT_IN_TIME_STATUS = CURRENT_MEMBERSHIP_ONLY_PROVISIONAL
```

This status is not survivor-bias-free. Current constituent lists may be useful for dashboard coverage, API plumbing, and integration testing, but they must not be represented as clean historical research universes.

## Required Future Inputs

- Historical benchmark membership with effective start and end dates.
- Stable security identifiers with ticker mapping history.
- Delisting dates and delisting returns where applicable.
- Corporate-action aware price, volume, shares, and market cap histories.
- Vendor/source metadata for each observation.

## Implementation Boundary

The helper `get_universe_members(universe_name, as_of_date)` reads universe membership artifacts and applies the membership-window rule above. If the artifact only contains current membership, the response remains marked `CURRENT_MEMBERSHIP_ONLY_PROVISIONAL`.

The workstation must not use future membership information for past backtests.
