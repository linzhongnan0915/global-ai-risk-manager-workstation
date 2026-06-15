# Strategy Entity Inventory

Phase: Active Strategy Count Reconciliation

## Correct Count Contract

Current active top-level strategy sleeves are:

| Category | Count | Treatment |
| --- | ---: | --- |
| Ordinary standalone active strategies | 16 | Each receives one top-level sleeve. |
| Combined active strategy | 1 | Receives its own top-level sleeve and internally equal-weights the 16 ordinary active strategies. |
| Current top-level active strategies | 17 | Top-level sleeve weight is `1/17`. |
| Pending candidates | 1 | `#000018` / `WQ_ALPHA_018`; current sleeve is N/A until admission. |
| Total registry entities | 18 | 16 ordinary + Combined + pending `#000018`. |

There is no missing `#000017` ordinary strategy slot in the current product contract. The 17th active strategy is `#COMBINED`.

## Combined Strategy

`#COMBINED` is an active top-level strategy. It receives its own top-level capital allocation like every other active strategy, and its strategy is to invest equally across all currently active ordinary strategies.

Current accounting:

| Field | Value |
| --- | ---: |
| Top-level active sleeves | 17 |
| Top-level sleeve weight | `1/17` |
| Combined internal constituents | 16 |
| Combined internal constituent weight | `1/16` |
| Pending post-admission sleeves | 18 |
| Pending proposed sleeve weight | `1/18` |

`#000018` remains excluded from current top-level active capital and from Combined internal membership until its admission gate is satisfied.
