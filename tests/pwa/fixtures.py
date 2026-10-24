"""Small real dashboard exports for browser tests (no optimizer changes)."""
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from build_plan_dashboard import build

base = Path(sys.argv[1])
base.mkdir(parents=True, exist_ok=True)
for label, target in [('first', 'ankh-4'), ('second', 'metronome-4')]:
    folder = base / label
    folder.mkdir(exist_ok=True)
    def write(name, fields, rows):
        with (folder / name).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    schedule = [dict(slot=1, phase=1, ship='henerprise-1', target='ankh', event_bonus=False, start_hour=8, end_hour=17.6),
                dict(slot=2, phase=2, ship='henerprise-1', target='meteorite', event_bonus=True, start_hour=24, end_hour=33.6),
                dict(slot=1, phase=3, ship='henerprise-1', target='none', event_bonus=False, start_hour=48, end_hour=57.6)]
    write('schedule.csv', list(schedule[0]), schedule)
    plans = [dict(slot=r['slot'], phase=r['phase'], ship=r['ship'], target=r['target'], event_bonus=r['event_bonus'],
                  launches=1, total_hours=9.6, total_fuel_T=25, curiousity_T=15, kindness_T=10, resilence_T=0, integrity_T=0) for r in schedule]
    write('launch_plan.csv', list(plans[0]), plans)
    write('craft_plan.csv', ['material_id', 'crafts'], [dict(material_id=target, crafts=2)])
    balance = [dict(material_id=target, starting_inventory=1, expected_drops=0, crafted=2, consumed=0, expected_remaining=3)]
    write('material_balance.csv', list(balance[0]), balance)
    write('event_windows.csv', ['phase', 'start_hour', 'end_hour', 'event_bonus'], [
        dict(phase=1, start_hour=0, end_hour=24, event_bonus=False),
        dict(phase=2, start_hour=24, end_hour=48, event_bonus=True),
        dict(phase=3, start_hour=48, end_hour=72, event_bonus=False)])
    (folder / 'plan_metadata.json').write_text(json.dumps(dict(target=target, parallel=3, horizon_hours=72,
        max_launches_per_hour=1, max_total_launches=3, max_launches_per_day=0,
        targeting_profile_names={'none': 'Untargeted', 'ankh': 'Tungsten Ankh', 'meteorite': 'Gold Meteorite'},
        optimization=dict(mode='balanced', status=0, guarantees={'crafts': {'proven': True, 'value': 2, 'bound': 2, 'gap': 0}},
                          timing={'solver_seconds': 5, 'additional_polish_seconds': 2, 'optimization_elapsed_seconds': 1}))))
    build(folder, base / (label + '.html'))
