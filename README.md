# EggIncVirtualShip

Run the optimizer with Python, NumPy, pandas, and SciPy installed:

```sh
python optimize_reggference.py --inventory inventory.csv
```

Inventory is optional. Without it, all starting counts are zero. Supply a UTF-8
CSV with exactly these columns (column order may vary):

```csv
material_id,quantity
metronome-3,9
geode-3,4
lens-3,8
```

Counts must be nonnegative whole numbers, at most 9007199254740991. Duplicate
materials, unknown identifiers, and malformed rows are rejected. Identifiers
must appear in the recipe or drop data; omitted materials default to zero.
Owned artifacts are used directly, without also crediting their ingredients.
Known materials outside the target recipe graph are accepted and reported.

The optimizer maximizes newly crafted `metronome-4` artifacts. Already-owned
`metronome-4` counts are added once to the total achievable quantity; they are
not included in `craft_plan.csv` as new crafts. Inventory and expected drops
are separate quantities. `material_balance.csv` adds a `starting_inventory`
column; its remaining balance is inventory + drops + crafted - consumed.
All other CSV columns retain their meanings. The generated offline dashboard
at `results/plan.html` shows inventory and the new/owned target breakdown, and
can still read older material balance CSVs without the inventory column.

Run the tests with:

```sh
python -m unittest discover -s tests -v
```

### Configurable runner and crafting targets

On macOS (system Bash 3.2 or newer) or Linux, prepare Python 3 dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install numpy pandas scipy
./run_optimizer.sh
```

Edit the clearly marked configuration section in `run_optimizer.sh` for the
planning horizon, fuel, ship slots, events, solver time, inventory path, and
repeatable sleep/no-launch windows. The runner uses `.venv/bin/python` when
available, otherwise `python3`. All relative paths, including CLI overrides,
are resolved from the project directory, even when launched elsewhere.

```sh
./run_optimizer.sh --target ankh-4 --days 30
/path/to/EggIncVirtualShip/run_optimizer.sh --target metronome-4 --events 0
./run_optimizer.sh --sleep 12:00-13:00 --no-launch 12.5-13.25
```

Scalar CLI overrides take precedence over configuration defaults. Repeatable
`--sleep` and `--no-launch` overrides add windows; edit the configuration arrays
to remove default windows. Set `INVENTORY_FILE=""` to run without inventory.
Set `OPEN_DASHBOARD=true` to open the generated dashboard on macOS after success.

`--target` defaults to `metronome-4` and accepts any recipe result ID, including
`ankh-4`. Only the selected target's recursive recipe tree is crafted. Existing
target artifacts count toward the total, separately from newly crafted items.
The shared `data/inventory.csv` includes materials from both recipe trees.
Edit its quantities to reflect actual owned items. Runs never rewrite it,
subtract planned crafting, add predicted drops, or reset it when switching targets.
Missing inventory files and invalid entries are errors; missing material rows
mean zero owned items.

The runner writes `results/metronome-4/` or `results/ankh-4/`, each with
`plan.html`, CSV exports, and `plan_metadata.json` identifying its target and
missing/unknown drop data. `--output-dir PATH` overrides the entire output path.
The direct Python CLI retains its original `results` output default.
Dashboard progress is keyed by both target and schedule. Older plans without
metadata default to the metronome target.

No drop rates are fabricated for new recipe materials. Materials without known
drops are reported in the console and metadata and can still come from inventory
or crafting. Blank/non-numeric drop values are reported as unknown rather than
measured zero. Supply verified rates in the existing expectations CSV format
(or select another CSV with `--expectations`) to make those sources available.
A feasible time-limited solution is explicitly reported as uncertified.

Currently, `titanium-bar-3` and `titanium-ore-3` have no ship drop rows.
Their crafting chain is limited to owned inventory. Existing ankh and meteorite
drop rows remain usable, so ankh plans can still be feasible.

### Rolling launch limit

```sh
./run_optimizer.sh --max-launches-per-hour 2
.venv/bin/python optimize_reggference.py --max-launches-per-hour 2 --days 3
./run_optimizer.sh --max-launches-per-hour 0
```

The Python CLI defaults to `0` (unlimited, preserving the original model).
The runner configuration defaults to `MAX_LAUNCHES_PER_HOUR=2`. Only launches
count, across all slots combined; returns do not count. Windows are half-open:
launches at 08:00 and 09:00 are exactly an hour apart and can reuse capacity.
The limit is rolling, including across wake-up and event boundaries.

A positive limit uses an individual-launch, continuous-time MILP. It jointly
chooses launch times, ships, slots, and event phases, alongside crafting and
fuel allocation. Sorted launch times satisfy `t[i + limit] >= t[i] + 1 hour`.
Slot-ready times prevent overlapping missions. Exported times come directly
from the solver, without shifting or rounding; an independent validator checks
the rolling rule and slot overlap before export (numerical tolerance 1e-7 hours).
The dashboard and `plan_metadata.json` record the configured limit.

This formulation is larger than the unlimited aggregate model, especially for
long horizons and many sleep/event phases. Use a shorter horizon or `--ships`
to reduce model size when necessary. A time limit can leave an uncertified
feasible solution or no solution; the optimizer reports either explicitly.
No launches is normally feasible, even if no new target can be crafted.
The existing one-second guard before event/sleep phase ends is retained.

### Solver progress and performance

```sh
./run_optimizer.sh --verbose-solver --solver-seconds 120
.venv/bin/python optimize_reggference.py --days 26 --max-launches-per-hour 2 --verbose-solver
.venv/bin/python benchmarks/benchmark_optimizer.py --label current
```

Progress is flushed immediately: before construction, before each solve, and
when each solve returns. Output includes model size, construction time, actual
solver runtime, solver status, best feasible objective, bound, and gap when
available. `--verbose-solver` enables HiGHS' own progress log; the runner also
has a `VERBOSE_SOLVER` switch. Stage timings and final status/gap are saved in
`plan_metadata.json`.

With a positive launch limit, a continuous relaxation of the aggregate model
first supplies a craft upper bound. A second LP minimizes launch count at the
rounded-down bound to propose a compact initial scheduling problem. These LP
solutions are estimates, not valid schedules. The continuous-time scheduling
MILP then jointly chooses ships, phases, slots, and exact launch times. Ship
selection depends only on event multiplier, with separate phase selection,
avoiding a binary variable for every ship/phase combination. If the candidate
cannot reach the upper bound, the launch capacity is expanded toward the full
safe bound while budget remains. Timed-out attempts never exclude a plan.
Only a feasible schedule attaining a proven bound (or a full-model proof) is
reported as globally optimal. A launch-capped subproblem's local optimum is
explicitly distinguished from a global proof.

`--solver-seconds` is passed as HiGHS' `time_limit`. Rate-limited runs share a
budget across stages; each call receives only its allocated remaining time.
The budget excludes initial input/aggregate construction. HiGHS may overrun
its limit in presolve or other noninterruptible operations, and Python model
construction also takes time; this is not a hard process deadline.
The benchmark runner uses a separate wall-clock cutoff and unique output
folders, recording timeouts without reading stale output files.

Feasible incumbents are retained when a later solve times out. An inventory-only
seed supplies a valid no-launch plan when scheduling finds nothing better. If
an unlimited solve finds no incumbent at its limit, an explicitly labelled
zero-launch, zero-new-craft fallback is exported. These are feasible fallbacks,
not evidence of optimality or useful new production. Unknown gaps remain
unavailable; no fabricated zero gap is reported.

See [the benchmark report](benchmarks/REPORT.md) for measurements and remaining
performance limits. Tests include solver option forwarding, time-limit
incumbent retention, fallback status, and failed-scheduling refinement.
