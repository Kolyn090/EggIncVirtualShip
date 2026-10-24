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
