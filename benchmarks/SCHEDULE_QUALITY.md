# Schedule-gap investigation and validation

> Historical report: measurements below used the former global launch-rate
> semantics. Current `--max-launches-per-hour` is independent per ship slot;
> the cross-slot staggering described below no longer applies.


The exact CSV behind the quoted 404.6-hour example was not supplied. Existing
local exports, model constraints and representative controlled cases were
inspected instead. The example was also covered by a 404.6-hour gap-partition test.

## Findings

- The old dashboard used `sleeps.some(...)`: any blackout overlap labelled the
  **entire** gap “Sleep / no launch.” That was a presentation error. Repeated
  nightly windows do not turn hundreds of available hours into sleep.
- An existing 100-day rate-limited export has a 1,136.1-hour gap in slot 2, from
  hour 39.9 to 1176. The next mission is boosted; the event starts at hour 1176.
  That export has no sleep restrictions. Every mission's actual duration,
  launch, completion, event eligibility, slot overlap, horizon and rolling rate
  passed the independent validator. Given that mission's selected boosted phase,
  it cannot launch before 1176. This supports event waiting for that interval,
  not a claim that the entire time-limited crafting plan is globally optimal.
- The old crafting objective had no fuel-allocation or timing tie-break. Start
  variables could take late feasible values within event/awake phases, and
  equivalent craft solutions could contain surplus missions or fuel blocks.
- Rate limits explain short staggering at event starts: two launches can occur
  together, but a third must be at least an hour later. They do not justify a
  hundreds-of-hours gap on their own. Returns never count as launches.

## Representative before/after

Both runs use ankh-4, 26 days, 500T fuel, three slots, only henerprise-3,
one hypothetical 48-hour 2x event, rolling limit 2, zero inventory, and a
5-second primary budget. The new run has a separate 5-second polishing budget.
Primary craft maximum was proven in both versions for this configured search
space. This is a correctness/quality comparison, not a runtime benchmark.

| Metric | Before | After |
|---|---:|---:|
| New target crafts | 5 | 5 |
| Allocated fuel | 500T | 420T |
| Actual fuel consumed | 420T | 420T |
| Missions | 6 | 6 |
| Last completion | hour 374.3997 | hour 365.8 |
| Largest gap between missions within a slot | 9.5997 h | 0 h |

The optimized launches occur at hours 288, 288, 289, 326.4, 326.4, 327.4;
all are in the event [288,336). Completions are 38.4 hours later. Slot reuse
and all rolling-hour windows are valid, including simultaneous launches.
Without the event, the same ship/fuel/horizon configuration has a proven
maximum of 2 crafts, and finishes its five required missions by hour 76.8.
Thus event waiting is beneficial for the 5-craft plan. Artificially filling the
initial idle period would waste fuel or alter the plan; no filler missions were
added. A further run with daily sleep and an explicit blackout generated a
validated plan under those additional restrictions.

Synthetic timing tests isolate the other cause: two one-hour missions in one
normal phase, with the second placed at hour 600, compact to hours 0 and 1.
When the second mission must use a boosted phase starting at hour 400, it moves
to hour 400 and the necessary 399-hour event wait remains.

## Model and proof scope

The craft count is fixed exactly for secondary stages. Objectives are sequential:
allocated fuel, consumed fuel, completion makespan, earlier launches/phases,
then mission count. A previous objective is locked before the next is solved.
Time-limited candidates are retained only when feasible and non-worsening; an
unproved priority stops lower-priority searches. Craft proof status remains
separate from secondary statuses.

Rate-limited polishing uses the winning launch-cap model, so secondary optimality
is scoped to that cap. Unlimited aggregate completion optimization uses only
nonempty phases; empty future days do not force late completion. Its early-phase
objective is followed by an exact fixed-plan timing LP. That LP fixes mission
identities, phases, slots and global order and optimizes makespan then start times,
with rolling and slot precedence constraints inside the optimization. It does
not claim global timing optimality over other mission orders or phase choices.
These scopes, objectives, statuses and accepted values are exported in metadata.
No timestamps are rounded or shifted by the dashboard.

## Dashboard

A long gap is one fixed-width, expandable card. Disjoint interval segments and
totals distinguish sleep, explicit no-launch, their overlap, idle/waiting and
possible event waiting. A candidate event reason is explicitly qualified, not
presented as a proof. Legacy merged blackouts remain labelled as unclassified
sleep/no-launch portions. Filtering never turns hidden missions into idle time.
Card sizes, scrolling, completion persistence and progress identity are retained.

## Reproduce and test

```sh
.venv/bin/python optimize_reggference.py --target ankh-4 --days 26 --ships henerprise-3 --events 1 --max-launches-per-hour 2 --solver-seconds 5 --polish-seconds 5 --output-dir results/quality-26
.venv/bin/python optimize_reggference.py --target ankh-4 --days 26 --ships henerprise-3 --events 0 --max-launches-per-hour 2 --solver-seconds 5 --polish-seconds 5 --output-dir results/quality-26-no-event
.venv/bin/python -m unittest discover -s tests -v
```

28 tests pass, including long gaps with repeated/overlapping restrictions,
beneficial event waiting, equivalent optima, simultaneous/nearly simultaneous
launches, time-limited secondary solves, dashboard rejection of invalid plans,
and JavaScript boot/gap-render/checkmark-persistence tests with a mock DOM.
This is not a manual browser or mobile rendering test.
