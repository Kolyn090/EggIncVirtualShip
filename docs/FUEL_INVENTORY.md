# Launch planning from existing fuel

Fuel configuration and crafting strategy are independent options. `--fuel-mode`
selects the fuel rules; the existing `--mode balanced|max-crafts` selects the
optimization strategy. Neither changes the crafting target, recipe data or
expected-drop assumptions.

## Two fuel modes

| Fuel mode | Availability | Fuel units/configuration |
| --- | --- | --- |
| `default` (unchanged default) | Choose allocations for the four historically budgeted fuels | `--fuel 500` is still 500T total; `--fuel-step 5` still allocates each type in 5T blocks. Humility remains outside this budget. |
| `existing_inventory` | Exactly the supplied initial stock of Curiosity, Kindness, Resilience and Integrity; Humility is always Unlimited and occupies no finite tank capacity | Repeat `--initial-fuel FUEL=QUANTITY` for finite fuels. Missing finite fuels are zero. Existing `--fuel` and `--fuel-step` have no effect on availability/allocation in this mode. |

This project uses **Virtue mission fuels**. It does not use a normal-universe
Tachyon/Dilithium/Antimatter/Dark Matter tank or convert those eggs to Virtue
fuel. Supported inputs are:

| Recommended input name | Existing CSV identifier | Fuel |
| --- | --- | --- |
| `curiosity` | `curiousity` | Curiosity |
| `kindness` | `kindness` | Kindness |
| `resilience` | `resilence` | Resilience |
| `integrity` | `integrity` | Integrity |
| Not needed (`humility` accepted for old commands) | `humility` | Humility: Unlimited |

Fuel names are case-insensitive. The legacy CSV spellings `curiousity` and
`resilence` are also accepted. Unknown fuel names and duplicate entries
(including aliases for the same fuel) produce errors; quantities are never
silently added together.

Humility requires **no** `--initial-fuel` entry. Legacy quantities such as
`--initial-fuel humility=0` or `humility=1T` remain accepted and validated, but
are ignored: they cannot limit launches or add finite tank capacity. Ships
requiring only Humility can launch with all four finite fuels at zero, subject
to the normal scheduling, availability and launch-count constraints.

`data/mission.csv` now includes explicit Humility costs, checked against
`MissionType.virtueFuels` in the pinned shared wasmegg library at
`8a9e04d299dba00af4b34ddf46241665fee30044`. The four original cost columns are
unchanged. Heavy and early ships consume Humility despite being free on the
default mode's four budgeted axes. Fixed-inventory mode tracks that usage but
does not constrain it or subtract it from finite inventory.
For custom datasets, all five fuel columns must be explicit finite nonnegative
numeric **T per launch**; a missing cost is an error, not a free fuel type.
Source-confirmed zero costs remain valid.

## Quantity formats

`--initial-fuel` quantities are eggs, parsed using exact decimal arithmetic:

| Input | Meaning |
| --- | --- |
| `500B` | 500,000,000,000 eggs |
| `1T` | 1,000,000,000,000 eggs |
| `1.5T` | 1,500,000,000,000 eggs |
| `250.5B` | 250,500,000,000 eggs |
| `0` | Zero eggs |
| `1000000000000` | One trillion eggs |

Suffixes are case-insensitive. Plain numbers on this **new** parameter are egg
counts (`1e12` is also accepted as an exact numeric value). Existing numeric options keep their original units: `--fuel 500` and
`--fuel-step 5` are T, not egg counts. Negative values, NaN/infinity, unknown
suffixes, comma separators and malformed quantities are
rejected for `--initial-fuel`.

## Run the optimizer

Prepare the existing Python environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Example using stored fuel, three slots, a hypothetical capacity event, sleep
and the existing per-slot rolling launch-rate constraint:

```sh
.venv/bin/python optimize_reggference.py \
  --fuel-mode existing_inventory \
  --initial-fuel curiosity=120T \
  --initial-fuel kindness=80T \
  --initial-fuel resilience=250B \
  --initial-fuel integrity=50T \
  --mode balanced --target ankh-4 --days 26 --parallel 3 \
  --ships henerprise-1,henliner-1 \
  --events 1 --event-hours 48 --event-multiplier 2 \
  --sleep 23:00-08:00 --max-launches-per-hour 1 \
  --max-total-launches 12 --solver-seconds 8 --polish-seconds 2 \
  --output-dir results/fuel-inventory-validation/26-day
```

`--ships` should reflect your available/unlocked ships, as in existing mode.
Omit it to keep the existing configured mission catalog. Existing `--inventory`
still supplies actual artifacts/materials independently of fuel stock.
Omitting all entries supplies zero finite fuel and unlimited Humility. This
still allows Humility-only missions and crafting from starting materials.
Custom genuinely free missions also remain usable.

Without the new flags, existing commands still select the original model:

```sh
.venv/bin/python optimize_reggference.py --fuel 500 --fuel-step 5 --days 26
```

## Configure `run_optimizer.sh`

No JSON configuration system was added. Use the runner's existing Bash
configuration section. A complete fixed-stock example is:

```bash
OPTIMIZATION_MODE="balanced"
TARGET="ankh-4"
DAYS=26
FUEL=500                         # Used only by default fuel mode
FUEL_MODE="existing_inventory"
INITIAL_FUEL=(
  "curiosity=120T"
  "kindness=80T"
  "resilience=250B"
  "integrity=50T"
)
PARALLEL=3
MAX_LAUNCHES_PER_HOUR=1
MAX_TOTAL_LAUNCHES=12
MAX_LAUNCHES_PER_DAY=0
EVENTS=1
EVENT_HOURS=48
EVENT_MULTIPLIER=2
FUEL_STEP=5                      # Used only by default fuel mode
SLEEP_WINDOWS=("23:00-08:00")
NO_LAUNCH_WINDOWS=()
INVENTORY_FILE="data/inventory.csv"
OUTPUT_DIR="results"
SOLVER_SECONDS=8
POLISH_SECONDS=2
VERBOSE_SOLVER=false
OPEN_DASHBOARD=false
```

Run `./run_optimizer.sh`. Shell paths still resolve relative to the project.
Explicit CLI stock values replace the configured value for that fuel:

```sh
./run_optimizer.sh --initial-fuel curiosity=100T --days 30
./run_optimizer.sh --fuel-mode default --fuel 500
```

Selecting default mode omits configured stock values. Repeating the same fuel
twice explicitly on the CLI is still an error. The runner's committed defaults
remain `FUEL_MODE="default"` and `INITIAL_FUEL=()`.

## Model and reporting

The existing crafting, targeting, material inventory, timing, slot, sleep,
no-launch, horizon, launch-cap and event constraints are reused. For each of
the four finite fuels:

```text
sum(actual per-launch cost × selected launches) ≤ starting stock
remaining stock = starting stock − exact total launch costs
```

There is no replenishment decision. Launch counts are integers. Exact rational
finite costs are reduced to integer common units separately for each finite fuel, and stock
is floored to those cost units. This removes only unusable fractional units,
never a feasible integer launch combination. It applies inside the aggregate
model, continuous-time scheduling model and craft-bound relaxation, not as a
schedule edit. An independent rational validator recomputes all five totals
from actual selected launches before export, with **zero overspend tolerance**
for the four finite fuels. No Humility capacity constraint or inventory-based
launch bound is added to any model, including resource relaxations and the
continuous-time model. Its per-launch costs remain unchanged and are reported.
Fractional input stock smaller than the common launch-cost unit remains unused.

In `balanced` strategy the priorities remain crafts, launch count, fuel, then
completion/earlier launches. Since initial allocations are fixed in this fuel
mode, the fuel tie-breaker minimizes **consumed finite fuel across the four stored types**,
using integer common units. It never trades crafts or launch count for fuel.
The `max-crafts` strategy retains its existing craft-focused behavior and skips
secondary minimization. Time-limited feasible results retain their existing
proof-status reporting and are not labeled optimal without a certificate.

`fuel_allocation.csv` retains `fuel`, `used_T`, `allocated_T` and `unused_T`.
In fixed-stock mode, `allocated_T` means the supplied initial stock, and
`unused_T` is its exact unused remainder for finite fuels. Humility has
`unlimited=true`; its numeric starting/allocation/remaining fields are blank
in CSV and null in JSON, and its starting/remaining display fields are
**Unlimited**. `used_T` and `consumed_eggs` still contain actual Humility usage.
It has no percentage consumed. Additional columns include
`fuel_name`, `starting_T`, `remaining_T`, `percentage_consumed`, exact egg-count
strings, and readable `starting`/`consumed`/`remaining` values. Numeric T columns
are written as exact decimal text. Zero starting stock has no meaningful
percentage and is shown as a dash in the dashboard.
The launch CSV's `humility_T` and `total_fuel_T` still record actual mission
usage, including Humility. Only finite tank summaries and the fuel-minimization
objective exclude it; an actual fuel requirement is never changed to zero.

`plan_metadata.json` records `fuel_mode`, `fuel_types`, `fuel_inventory`,
`fuel_inventory_totals`, `unlimited_fuels=["humility"]` and `fuel_validation_tolerance_eggs`.
Combined starting, consumed and remaining totals contain only finite fuels;
Humility usage is displayed separately and never consumes tank capacity.
`optimization.guarantees.consumed_fuel` describes the fixed-craft/launch finite-fuel
minimum. `allocated_fuel` is labeled as fixed input rather than an optimized
decision. Completion proofs remain conditional on preceding priorities.

The optimizer automatically creates `plan.html`. To regenerate it:

```sh
.venv/bin/python build_plan_dashboard.py --results results/fuel-inventory-validation/26-day
```

The dashboard shows the mode, starting stock, planned consumption, remaining
stock and percentages in B/T notation, plus an Unlimited Humility row with
its actual usage. This is the finite stock remaining **after all
planned launches**, not a live tank reading that changes with checklist marks.
No input inventory or runner configuration is modified after planning.

Generated HTML imports into the same offline PWA. Icons, S/M/E badges, yellow
latest-completion highlighting, timestamps, backups and the single-active-plan
workflow are unchanged. Old metadata/CSV exports without fuel-mode fields
continue to use the legacy four-fuel view. After template changes, run
`npm run build:pwa` to refresh the committed offline bundle/cache version.
Older existing-inventory HTML files can still be imported: the PWA shows
Humility as Unlimited and recalculates displayed totals from the four finite
fuel rows. Existing schedules are not automatically re-optimized; rerun the
optimizer to benefit from the corrected unlimited-Humility launch choices.
Old optimality certificates used different fuel assumptions, so these archived
plans are labeled legacy until re-optimized rather than claiming a current maximum.

## Validation and limits

The MILP still uses floating-point solver machinery for scheduling and expected
drops. Fuel constraints use exactly representable integer coefficients; each
coefficient/capacity must be at most `2^50`, and initial quantities at most
`10^27` eggs. Pathological decimal precision/exponents are also rejected.
Unsupported numeric scaling is rejected, never rounded into extra
fuel. Post-solve fuel accounting is exact regardless of solver tolerances.
Existing solver deadlines, expected-drop limitations, hypothetical event
assumptions and chosen research/star/ship-availability settings still apply.

Validation commands:

```sh
.venv/bin/python -m unittest discover -s tests -v
npm test
npm run test:pwa
PWA_TEST_SUBPATH=1 npm run test:pwa
```

The new Python tests cover zero/insufficient/exact stock, one-egg shortages,
all-fuel costs, competing ships, unused fuel, mixed decimal notation, malformed
quantities, genuine zero costs, default-mode compatibility, material inventory,
timed/event/sleep/day/rate limits, both search strategies, revalidated incumbents,
time-limited results and fuel minimization without craft loss. Humility-only
Heavy missions are tested with omitted, zero and tiny legacy Humility stocks,
zero finite fuel, both scheduling models and both search strategies. Browser tests
import a real optimizer-generated fixed-stock export, check B/T reporting and
icons/badges, and save/reload/restore checklist backups offline.

Representative runs with the exact command above and its 30-day `max-crafts`
variant (same stock, ships, sleep, event and launch limits):

| Horizon / strategy | Expected ankh-4 crafts | Launches | Finite fuel consumed | Finite fuel remaining | Completion day | Reported total time | Proofs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 26 days / balanced | 6 | 7 | 175T | 75.25T | 13.7333 | 8.28s | Crafts, launches, consumed finite fuel and completion proven in the exact aggregate model |
| 30 days / max-crafts | 6 | 8 | 200T | 50.25T | 16.1333 | 1.47s | Crafts proven; secondary objectives not solved |

Both began with 250.25T across the four finite types and unlimited Humility;
neither supplied a Humility inventory. Their separately reported Humility use
was 70T and 80T, respectively, with starting/remaining Humility shown as
Unlimited. Both left Resilience (250B) and Integrity (50T) unused. Every per-fuel
total was recomputed from the actual exported missions. Runtime and equivalent
optimal schedules can vary.

A real-data zero-finite-stock smoke test (`heavy-1`, target `ankh-2`, two days,
eight-launch cap and two already-owned `titanium-bar-3`) also proved one expected
craft using three Heavy missions: zero finite fuel, 0.15B Humility usage and
Unlimited Humility availability. No `--initial-fuel` entries were supplied.
