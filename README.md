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
