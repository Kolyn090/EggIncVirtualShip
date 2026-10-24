# Solution quality and scheduling comparison

Baseline: `b526002`. Cases use the same repository data/inventory, metronome-4,
500T fuel, three slots, one 48-hour 2x event, 00:00–11:00 daily sleep, and
a per-slot rolling limit of 2. Budgets: 10 seconds for primary optimization,
5 seconds for secondary optimization, 40-second process cutoff.
Inventory SHA-256: `872a6d72996c5056600318a5d480752e3d23321c2b727511b3e8bde9b3ad1a22`.

The old backend is SciPy/HiGHS 1.8; the new backend is pinned native HiGHS
1.12.0 with one solver thread and incumbent warm starts. BLAS/OMP thread counts
were set to 1. These are single short-budget comparisons, not statistical
speedup claims. Solver limit overruns and construction/export time are included
in wall time. The exact 13-launch plan in the request was not supplied; this
is a controlled comparison using the checked-out inventory and data.

| Days | Version | New crafts | Allocated T | Consumed T | Launches | Completion day | Wall seconds | Craft bound | Craft gap |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 26 | before | 2 | 500 | 140.000 | 14 | 15.058 | 11.70 | 10 | 400.0% |
| 26 | after | 4 | 0 | 0.000 | 526 | 21.792 | 16.57 | 8 | 100.0% |
| 30 | before | 4 | 500 | 490.000 | 7 | 29.058 | 12.60 | 10 | 150.0% |
| 30 | after | 4 | 0 | 0.000 | 525 | 20.000 | 16.00 | 8 | 100.0% |
| 100 | before | 0 | 0 | 0.000 | 0 | no missions | 11.45 | 11 | 1100.0% |
| 100 | after | 4 | 5 | 0.560 | 598 | 53.031 | 28.52 | 11 | 175.0% |

**All six primary runs were time-limited; none proved the craft maximum.**
The 100-day baseline retained a zero-craft fallback, not a useful production plan.
Its legacy 1100% gap used a max(1, incumbent) denominator; a relative gap against
zero is undefined. The new implementation reports it unavailable rather than
reporting a fabricated finite percentage.
The new 26- and 30-day runs prove 0T is the minimum allocation for their fixed
4-craft incumbents. Completion minimum remains unproven in all three large new runs.
The 100-day fuel minimum is unproven. Fixed-order calendar timing is
proved only within its stated scope, not over all ship/order choices.

## Root causes

1. The former implementation built an individual-launch MILP even when ship
   durations plus nonoverlap already implied the per-slot limit. It then polished
   only a launch-capped model. The exact aggregate model now handles those cases.
2. Start/end big-M values were unnecessarily loose. The empty-phase bound now
   uses H minus phase end, and completion is linked directly to phase activation
   and workload with additional valid inequalities. Slots are symmetry-ordered
   by total launch count; positive-fuel launch counts also have fuel-based bounds.
3. Every SciPy stage was cold-started. Native HiGHS now receives the known
   feasible incumbent for full and secondary searches. A small restricted-phase
   seed gives a starting plan; its dual bound is never used as a global bound.
4. Consumed-fuel minimization previously preceded makespan, contrary to the
   requested ordering. The priorities are now crafts, allocation, completion,
   earlier launches, then mission count. A timed-out objective is locked at its
   best feasible value and lower-priority improvements are labelled conditional.
5. The old final timing LP fixed the original phase, so an ordinary mission
   assigned to a late day could not move earlier. The exact fixed-order temporal
   solver now permits any awake phase with the same event multiplier.
6. Zero-cost fuel rows are real input data: bcr-1, bcr-3, heavy-1, heavy-3 are
   explicitly zero in every fuel column among the currently eligible ships.
   Missing/nonfinite/nonnumeric/negative fuel is rejected, never filled with zero.

## Why the launch count can increase

The 30-day new plan uses 525 zero-cost launches to retain four crafts at proven
minimum allocation 0T. This is a direct consequence of fuel being prioritized
above makespan and launch count. Its missions are not filler: any individually
removable mission and surplus intermediate craft is eliminated while preserving
all target crafts/material balances. A different free-ship mix could be faster;
the global completion minimum is not proven. No new fuel costs or drop rates
were invented to force a preferred schedule. Correct input costs if the explicit
zeros are inaccurate, rather than treating blanks as zeros or changing objectives.

## Timing correctness and proof

In the aggregate route, selected counts, phase starts, last mission types and
cumulative durations encode a feasible within-phase sequence. Export reconstruction
uses the optimized start variables. The individual-launch model is still used
when a per-slot rate adds a real constraint (short missions). Both retain event
eligibility at actual launch time, sleep/no-launch exclusions, returns, slot
nonoverlap, fuel increments, inventory and the horizon.

The final temporal model fixes mission identities, event multipliers, slots and
per-slot order. Each start is bounded below by previous completion and the L-th
previous start plus one hour, with a domain equal to the union of compatible
awake phases. Forward propagation picks the least feasible point in that domain.
Induction proves it is componentwise earliest for those fixed choices, hence
minimizes makespan and total start time in that scope. It can move ordinary
missions across calendar phases; event waiting remains if the next required
boosted mission has no earlier compatible window. This is an exact temporal
solver, not an arbitrary dashboard timestamp adjustment. Phase/count CSV exports
are rebuilt from the resulting actual schedule.

## Limitations and validation

Large sleep-aware MIPs still have weak relaxations and many equivalent free-ship
plans. The 100-day solve still overran its requested time limit despite adaptive
presolve settings. Native HiGHS is not a hard process deadline. These changes
improve incumbents/reporting; they do not establish all global optima or a general
wall-time speedup. Longer budgets may be needed. A lower craft incumbent with
cheaper fuel is never substituted during secondary optimization.

37 tests pass, including early ordinary launches across phase boundaries,
beneficial event waiting, craft preservation during fuel minimization, no fuel
increase during completion improvement, independent per-slot rates, missing fuel
rejection, native/fallback agreement, time-limited labels, and dashboard/CSV
agreement. Each new benchmark export was independently checked for actual
durations, slot overlap, rate limits, event eligibility, sleep, horizon, fuel,
material balances, per-phase mission counts and dashboard summary values.

## Reproduce

```sh
.venv/bin/python -m pip install -r requirements.txt
git show b526002:optimize_reggference.py > /tmp/optimizer-before-quality.py
.venv/bin/python benchmarks/compare_solution_quality.py --label before --optimizer /tmp/optimizer-before-quality.py
.venv/bin/python benchmarks/compare_solution_quality.py --label after
.venv/bin/python -m unittest discover -s tests -v
```

The measurements above were collected with an equivalent subprocess harness
before saving the reusable driver. Logs/CSVs are in ignored
`results/quality-comparison/before-{26,30,100}` and `after-{26,30,100}`.
The reusable driver creates unique folders to avoid stale artifact reuse.
