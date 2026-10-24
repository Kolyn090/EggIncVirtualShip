# wasmegg expectations and launch targeting

The default CSV now comes from the repository's wasmegg loot observations, using
its original TypeScript calculations through Node. It is an empirical point
estimate, **not an exact game probability calculation or a simulation**. No
Python implementation of the drop formula was added.

## Regeneration

Install Node 20+ and Git, then run from the project root:

```sh
npm ci
node scripts/generate_ship_expectations.js
npm test
.venv/bin/python -m unittest discover -s tests -v
```

The script resolves its defaults from its own location, so it also works from
another directory. Its optional `--output`, `--config`, and `--recipe-dir` paths
resolve from the invoking directory. To validate a candidate without replacing
production data:

```sh
node scripts/generate_ship_expectations.js --output /tmp/expectations.csv
```

The checked-in wasmegg subtree lacks the parent monorepo's shared `lib`, protocol
files, and package manifest. On first regeneration, the headless adapter fetches
only the necessary shared directories from `carpetsage/Egg`, pinned to commit
`8a9e04d299dba00af4b34ddf46241665fee30044`, into ignored
`.cache/wasmegg-upstream`. This first run needs network access. Subsequent runs
use that verified checkout. Missing data/dependencies, a different checkout
commit, or modified tracked shared code cause errors; there is no legacy-data
fallback. The adapter bundles the original calculation functions without
modifying the checked-in wasmegg source. Protobuf enums are loaded from the
pinned protocol; unused UI helpers are isolated from the headless runtime.

When updating wasmegg, review compatibility with the pinned shared library,
update that pin deliberately if required, regenerate, and run the tests. Update
the matching loot snapshot as well; this is not a live loot-data download.
Metadata records the shared commit, local source hashes, configuration, material
mapping, legal/usable profile catalog, and CSV hash. Keep the CSV and metadata
together. A mismatched pair is rejected by the optimizer.

Generation validates all rows before replacement. The original data is preserved
as `data/ship_material_expectations.legacy.csv`; later runs never overwrite this
backup. Actual inventory is never changed by generation or optimization.

## Original functions and calculation

| Responsibility | Source and functions reused |
| --- | --- |
| Mission definitions, FTL classification, allowed targets | Shared `lib/missions.ts`: `allMissionTypes`, `targets`, `MissionType.isFTL` |
| Duration, capacity, quality, player settings | Shared `lib/missions.ts`: `boostedDurationSeconds`, `boostedCapacity`, `boostedMaxQuality`, `perfectShipsConfig` |
| Mission loot histograms by stars and target | Local `wasmegg/src/lib/loot.ts`: `getMissionLootData`, reading `wasmegg/data/loot.json` |
| Expected item units per launch | Local `wasmegg/src/lib/phases.ts`: `enumerateLaunchOptions`, its returned `supplyVector` |
| Artifact family, tier, quality, mission availability, recipes | Shared `lib/artifacts/data.ts`: `getArtifactTierPropsFromId`, `getArtifactFamilyProps`, `allPossibleTiers` |
| Human target names | Shared `lib/missions.ts`: `getTargetName` |

For each item tier, `enumerateLaunchOptions` sums its four rarity buckets and
divides by the selected mission/star/target profile's total recorded individual
drops, then multiplies by boosted capacity. The result is expected **units per
launch**, potentially greater than one. It is not the probability of at least
one drop. Rarities are combined because the optimizer models item counts, not
legendary crafting probabilities.

Targeting selects a different observed histogram. It can increase one family's
share and decrease another's by different amounts; no uniform targeting
multiplier is used. The wrapper supplies a DAG containing every source tier so
wasmegg retains all observed family choices rather than reducing targets to
one representative outside a particular crafting tree. Legal targets come from
the shared source; non-FTL missions get only `none`. Tutorial missions are
excluded as nonrepeatable. Missing observations do not create fictional targets.

## Player assumptions and data limits

`data/ship_expectations_config.json` defaults to maximum ship stars, FTL research
level 60, and Zero-G research level 10. An empty `shipLevels` object means the
original `perfectShipsConfig` maxima, not zero stars. Overrides use optimizer
ship-family names and source star counts, for example
`"shipLevels": {"henerprise": 7}` means seven stars. The data includes a zero-star bucket;
use the actual desired star count and do not subtract one. Regenerate after
changing settings. The optimizer reads generated duration/capacity metadata,
so timing uses the same configuration as expectations. Fuel costs remain the
explicit existing `data/mission.csv` costs; targeting never changes them.
The existing four-fuel budget excludes Humility, matching wasmegg's
`makeLaunchOption` accounting; some early missions are free on those four axes.

The default minimum sample threshold is 20 conservative equivalent missions:
`totalDrops / maxBoostedCapacity >= 20`, following wasmegg's own threshold.
This is a practical coverage filter, **not a statistical confidence guarantee**.
There are 33 repeatable mission definitions, 957 legal profiles, 533 usable
profiles, and 19,140 generated rows covering 20 recipe materials. The generator
emits all legal profiles, including those the optimizer cannot safely use.

CSV leading columns are
`ship,target,material_id,expectation_per_launch`, followed by
`status,observed_count,total_drops`:

- `empirical`: positive observed count and a usable profile; finite mean.
- `confirmed_zero`: outside the mission's quality range or unavailable from
  missions, with no contradictory positive observation; numeric zero.
- `unobserved`: a possible item with no observations in an otherwise usable
  profile; blank expectation, explicitly unknown.
- `unknown_profile`: missing/insufficient observations; blank expectation.

Unusable profiles are excluded completely. Unknown item supply in retained
profiles receives no credit in the model and remains identified in plan
metadata; it is never presented as a measured zero. Empirical data cannot
establish a true game's exact optimum, particularly for rare unobserved tiers.
Solver proofs concern this model's known point estimates and configured recipes.
Research changes scale source capacity/duration as implemented by wasmegg; they
do not invent unobserved conditional distributions.

## Identifier and recipe mapping

Recipe aliases map to source canonical families: `metronome` →
`quantum-metronome`, `ankh` → `tungsten-ankh`, `geode` → `tau-ceti-geode`,
`meteorite` → `gold-meteorite`, `lens` → `mercurys-lens`, and `actuator` →
`titanium-actuator`. Ordinary suffixes are one-based tiers; source `afx_level`
is zero-based. Full mappings are recorded in metadata. Stone-fragment targeting
IDs remain distinct from full-stone family IDs.

Two legacy ingredient names need explicit exceptions: `titanium-bar-3` is the
source T2 **bar** (`solar-titanium-2`), and `titanium-ore-3` is T1 **ore**
(`solar-titanium-1`). Their legacy suffixes are not their actual tiers. Neither
is silently mapped to T3 geogons, and inventory identifiers remain unchanged.

The supplied ankh recipes require two bars when making `ankh-2`; upstream
requires those bars when making `ankh-3` instead. Both supplied recipe files
contain this difference. **Supplied recipes are preserved**, and warnings with
both ingredient lists are recorded in metadata and reported during optimization.
Plans therefore use the user's recipes, not automatically corrected game recipes.

Recipes are discovered from every CSV under `data/artifact-recipes/`. Only the
selected target's recursive graph is optimized. Recipe keys are namespaced by
filename; identical duplicate definitions are deduplicated, and conflicting
recipes for the same result fail clearly. The old single-file location remains
supported for legacy/custom input directories without this directory.

Mission aliases preserve the optimizer's public ship IDs: `atreggies` →
`henliner`, `millenium-chicken` → `quintillion-chicken`,
`corellihen-corvette` → `cornish`, `chickfiant` → `defihent`, and
`chicken-heavy` → `heavy`. Mission suffixes identify short/standard/extended,
not stars.

## Optimizer and dashboard behavior

The existing optimization model jointly chooses a `(ship, target)` option,
launch time and slot. Every variant shares its base ship's duration and fuel
costs. Only exact same-ship Pareto-dominated options on required ingredient
supply are eliminated; no targeting-family heuristic restricts useful choices.
All existing inventory, event, fuel increments, horizon, sleep, slot overlap,
and per-slot rolling launch-rate constraints remain in force and are validated
before exporting. No dashboard timing adjustments are made.

Both `schedule.csv` and `launch_plan.csv` gain a `target` column while retaining
public base ship IDs. The checklist, recommended ships, search and detailed
schedule show each target, with recommended groups separated by ship and target.
Progress identity includes targeting; legacy untargeted mission keys are
unchanged. Changing a target or schedule isolates completion checkmarks.

The optimizer can still explicitly read a legacy untargeted CSV with
`--expectations ship_material_expectations.legacy.csv`. It never selects this
file as a silent fallback.

## Validation results

`npm ci --ignore-scripts` and `npm test` passed (8 tests). A fresh sparse
bootstrap of the pinned shared source reproduced the published CSV byte for byte. The full Python suite
passed (44 tests), including a functional dashboard JavaScript test verifying
separate target groups and saved-progress identity. Coverage checks source
means, units versus probabilities, targeting redistribution, finite/unknown
values, tier aliases, legal targets, deterministic published output, inventory,
profile rejection, fuel/duration equivalence, schedule constraints and dashboards.

All 76 positive comparable untargeted legacy cells agree within the old CSV's
displayed rounding precision. The largest relative change, 2.874%, is the tiny
`cornish-1 / metronome-1` rate: 0.0012 versus about 0.00123449. The next is
0.7254%, `henerprise-1 / ankh-4`: 0.0033 versus about 0.00332394. No unexplained
large difference was found. Other legacy materials are outside the two current
recipe trees and remain in the preserved backup.

Actual representative commands, using the new default CSV:

```sh
.venv/bin/python optimize_reggference.py --target metronome-4 \
  --ships henerprise-1 --days 2 --fuel 100 --events 1 --event-hours 12 \
  --sleep 23:00-08:00 --no-launch 1.5-1.6 --max-launches-per-hour 1 \
  --inventory data/inventory.csv --solver-seconds 5 --polish-seconds 2 \
  --output-dir results/wasmegg-metronome

.venv/bin/python optimize_reggference.py --target ankh-4 \
  --ships henerprise-1 --days 2 --fuel 100 --events 1 --event-hours 12 \
  --sleep 23:00-08:00 --no-launch 1.5-1.6 --max-launches-per-hour 1 \
  --inventory data/inventory.csv --solver-seconds 5 --polish-seconds 2 \
  --output-dir results/wasmegg-ankh
```

| Craft target | New crafts | Launch targeting | Launches | Allocated / consumed fuel | Completion day |
| --- | ---: | --- | ---: | ---: | ---: |
| metronome-4 | 1 | geode | 2 | 50T / 50T | 1.15 |
| ankh-4 | 4 | meteorite | 3 | 75T / 75T | 1.15 |

Both cases proved crafts, fixed-craft fuel, and fixed-craft/fuel completion
optimality for the configured known-data model and selected ship. They launch
at hour 18 in different slots, during the actual event, finishing at hour 27.6;
all independent schedule and resource validations pass. Each generates its own
HTML dashboard. Source files, recipe files, and actual inventory are unchanged.

A broader 26-day check used the same sleep/rate/inventory settings, 500T fuel,
a 48-hour event, and the same five-second solver/two-second polishing budgets.
With `--ships henerprise-1,henerprise-3`, it found 10 feasible crafts, a bound
of 11 (10% solver gap), seven launches mixing geode and metronome targets,
490T allocated/consumed, and completion day 15.5333. Craft/fuel/completion global
optimality remained unproven. Native HiGHS spent about 39 seconds across stages,
including a substantial solver time-limit overrun; the reported actual runtime
and proof status were retained. With all ships available, the new targeting
profiles leave 271 nondominated options and 42,366 aggregate variables; the very
short budget found only the valid zero-launch fallback (upper bound 15),
explicitly unproven. These expose remaining scheduling/solver performance
limitations; expanding targeting does not resolve those existing limitations.

## Changed files

- `scripts/generate_ship_expectations.js`, `scripts/wasmegg/runtime.js`:
  original-source wrapper, validation, provenance and safe regeneration.
- `package.json`, `package-lock.json`, `.npmrc`, `.gitignore`: pinned headless
  Node tooling and project-local ignored caches.
- `data/ship_expectations_config.json`, `data/ship_material_expectations.csv`,
  its `.metadata.json` and `.legacy.csv`: player settings, validated profiles,
  reproducibility/coverage details and original backup.
- `mission_profiles.py`, `optimize_reggference.py`: generic recipes, validated
  profile loading, dominance pruning and joint targeting choices/exports.
- `build_plan_dashboard.py`: targets in launch UI, summaries and progress IDs.
- `tests/expectations.test.js`, `tests/test_profiles.py`, `README.md`, this report:
  regression tests and usage/source documentation.
