# Optimizer performance benchmark

Baseline: commit `80df509`. Updated measurements: current implementation.
Cloud Linux, Python 3.12, SciPy 1.17.0 / HiGHS 1.8.0. Each case uses the metronome target,
zero starting inventory, 500T fuel, three slots, one 48-hour 2x event.
Sleep cases use 23:00–08:00. Limit cases use two launches per rolling hour.
Each case runs in a fresh Python process, with a 5-second solver budget and a separate
20-second process cutoff. OPENBLAS_NUM_THREADS=1 and OMP_NUM_THREADS=1; other HiGHS
defaults are unchanged. These are single short-budget measurements, not statistical
speedup claims or evidence of production-budget quality. End-to-end wall times include
Python startup, construction, solves, validation, and export. Timing can vary.

| Days | Sleep | Limit | Before wall | Before outcome | After wall | After outcome |
|---:|:---:|---:|---:|---|---:|---|
| 26 | no | 0 | 2.37s | 3 crafts, proven optimal | 1.62s | 3 crafts, proven optimal |
| 26 | no | 2 | 20.02s | wall cutoff; no result | 6.04s | 3 crafts, feasible; unproven |
| 26 | yes | 0 | 5.94s | no feasible incumbent; error | 5.83s | 0 new crafts, feasible zero-launch fallback; unproven |
| 26 | yes | 2 | 10.95s | no feasible incumbent; error | 5.93s | 0 new crafts, feasible zero-launch fallback; unproven |
| 100 | no | 0 | 1.02s | 4 crafts, proven optimal | 1.32s | 4 crafts, proven optimal |
| 100 | no | 2 | 20.02s | wall cutoff; no result | 5.98s | 1 craft, feasible; unproven |
| 100 | yes | 0 | 20.01s | wall cutoff; no result | 20.01s | wall cutoff; no result |
| 100 | yes | 2 | 20.09s | wall cutoff; no result | 6.35s | 0 new crafts, feasible zero-launch fallback; unproven |

The rate-limited cases now return validated plans before the cutoff, but short-budget
sleep cases only return zero-launch fallbacks. That is improved failure handling,
**not** a useful crafting solution. The 100-day unlimited/sleep case remains slow:
construction finished in under 0.2s but the solve did not return before the process cutoff,
despite HiGHS receiving a 5-second limit. Longer budgets/solver tuning remain necessary.

## Main bottlenecks and changes

- The old positive-limit model allocated a binary for every launch × ship × phase.
  At 26 days with sleep, it built 331,979 variables before solving. The new first
  scheduling subproblem had 1,707 variables, with expansion if the bound was not met.
  Those sizes are different search scopes: a smaller subproblem alone is not a proof.
- Ship/event-multiplier selection and phase selection are now factored, with equality
  linking the multiplier to the chosen phase. No minute-by-minute grid is introduced.
- Two small continuous aggregate relaxations provide a target upper bound and a
  launch-count suggestion. No integer scheduling is required in either relaxation.
- Scheduling starts with a compact launch cap, retains incumbents, and expands toward
  the full safe bound when necessary. Only a schedule attaining a proven upper bound
  (or a full-model proof) receives a global optimal status. A failed or timed-out
  attempt never excludes a feasible count plan.
- Big-M relaxations and slot symmetry still make integer scheduling difficult.
  Unlimited aggregate scheduling with many sleep phases remains an integer bottleneck.
- Every solve now reports requested limit, elapsed time, status, objective, bound and
  gap. HiGHS can overrun time limits in noninterruptible work; model construction
  also lies outside solver time. A process cutoff is a different measurement.

## Reproduce

```sh
git show 80df509:optimize_reggference.py > /tmp/optimizer-before-performance.py
.venv/bin/python benchmarks/benchmark_optimizer.py --label before --optimizer /tmp/optimizer-before-performance.py
.venv/bin/python benchmarks/benchmark_optimizer.py --label after
```

The baseline shown here was run with an equivalent eight-case subprocess harness
before the reusable harness was added. Each run retains logs, plan outputs and
`measurements.json` under a unique ignored `results/performance/` directory.
Current measurement artifacts: `results/performance/final-1792858661929769335`.

## Validation

19 existing/new tests pass, including rolling limits, phase boundaries, sleep, fuel,
inventory, solver option forwarding, time-limit incumbent retention, explicit
fallbacks, and refinement after failed scheduling. A real `--verbose-solver` smoke
run emitted HiGHS progress and generated its dashboard. Exported benchmark plans
were independently checked for material balances, fuel, slot overlap, rolling
launch limits, event multipliers, sleep exclusions and horizon completion.
