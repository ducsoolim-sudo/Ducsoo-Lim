# Automatic scoring validation

Status: development only; automatic release gate **not passed**.

## Reproducible runtime

- Engine: KataGo 1.16.3, official Eigen CPU Linux release.
- Stronger candidate: `b18c384nbt-uec.bin.gz`, upstream v1.12.0 model release.
- Candidate size: 97,610,638 bytes.
- SHA-256: `dd6a372c5496267347bd7c977b617f730f4d9198a2a075cc3d1a1047b4da5c4c`.
- Installer: `python install_engine.py /absolute/runtime/path --strong`.
- This is a reproducible older model, not the latest trained network.

## Observations

The initial 256/1024-visit run did not identify the expected dead group with
sufficient confidence in the nearly filled enclosed-death stress position. The
result remained `review`; automatic acceptance was blocked.

A separate diagnostic 32/128-visit run completed in 49.06 seconds on this CPU:

| Search | Actual visits | Black score lead | Ownership at white stone | Ownership deviation |
|---|---:|---:|---:|---:|
| Quick | 33 | -4.709 | 0.830 | 0.495 |
| Deep | 129 | -39.117 | 0.814 | 0.454 |

These inconsistent estimates fail the confidence and score-agreement checks. Do
not loosen thresholds just to pass this position. Nearly filled setup positions
are stress fixtures, not a representative completed-game dataset; these results
do not by themselves measure playing strength or typical production latency.
They do show that installing a stronger model does not establish a complete
Japanese adjudicator, and this CPU profile cannot yet support a prompt scoring
experience at the intended search budget.

## Harness changes

`check_engine.py` now checks automatic acceptance, rather than merely checking
that the program returns without crashing. Enclosed death and shared-liberty
fixtures must return `ready` with the expected dead stones/territory; an
unfinished position must return `review`. A failed gate exits nonzero. Use
`--visits QUICK DEEP` and `--case NAME` for explicitly labelled diagnostics;
default release-budget checks remain 256/1024 visits. `KATAGO_REPORT` writes an
incremental JSON report, preserving failed-case diagnostics.

Unit regressions additionally verify immediate ko recapture is illegal, recapture
after intervening play is allowed, and a possible no-result prediction cannot
become an automatically accepted score. Invalid probabilities and incomplete
search budgets are rejected.

## Remaining release requirements

1. A reviewed set of real completed 13x13 games plus authoritative exceptional
   Japanese-rules cases, including bent-four/replacement-life and repeating ko.
2. Exact expected outcomes and seki territory, not just model agreement.
3. Accuracy/automatic-acceptance-rate and p95 latency/memory results on the actual
   intended deployment hardware.
4. An engine/rules policy for cases that remain unresolved. Ownership estimates
   alone cannot supply a guaranteed Japanese-rules decision in every position.

Keep production and test deployment unchanged until these gates pass. No paid
compute has been provisioned.
