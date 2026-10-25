"""Load prior optimizer exports as witnesses, revalidating against CURRENT inputs."""
from pathlib import Path
import json
import math
import pandas as pd
from schedule_validation import validate_schedule
from fuel_inventory import fixed_fuel


def load_plan(directory, *, mission, available, hours, phases, event_phases, sleeps,
              args, groups, outputs, validate_resources, inventory, rate, fuel):
    directory=Path(directory)
    try:
        launches=pd.read_csv(directory/'schedule.csv');crafts=pd.read_csv(directory/'craft_plan.csv')
    except (OSError,ValueError) as exc:raise ValueError('Cannot read incumbent plan: '+str(exc)) from exc
    if not {'slot','ship','event_bonus','start_hour','end_hour'}<=set(launches.columns) or not {'material_id','crafts'}<=set(crafts.columns):
        raise ValueError('Incumbent CSV columns do not match optimizer exports')
    metadata=directory/'plan_metadata.json'
    if metadata.exists():
        previous=json.loads(metadata.read_text())
        if previous.get('target',getattr(args,'target','metronome-4'))!=getattr(args,'target','metronome-4'):
            raise ValueError('Incumbent crafting target does not match the selected target')
    keys={(mission.loc[key,'base_ship'],mission.loc[key,'drop_target']):key for key in available}
    counts={rid:0 for rid,_ in groups};recipes={output:rid for rid,output in outputs.items() if rid in counts}
    if crafts.material_id.duplicated().any():raise ValueError('Duplicate crafts in incumbent plan')
    for row in crafts.itertuples():
        if row.material_id not in recipes:raise ValueError('Incumbent craft is outside the current recipe tree: '+row.material_id)
        quantity=float(row.crafts)
        if not math.isfinite(quantity) or quantity<0 or quantity!=int(quantity):raise ValueError('Invalid incumbent craft quantity')
        counts[recipes[row.material_id]]=int(quantity)
    schedule=[]
    for row in launches.itertuples():
        pair=(row.ship,getattr(row,'target','none'))
        if pair not in keys:raise ValueError('Incumbent ship/target unavailable in current model: '+str(pair))
        flag=str(row.event_bonus).lower()
        if flag not in ['true','false']:raise ValueError('Invalid incumbent event flag')
        start=float(row.start_hour);end=float(row.end_hour);boost=flag=='true'
        phase=next((p for p,(a,b,bonus) in enumerate(phases) if bonus==boost and a-1e-8<=start<=b-1/3600+1e-8),None)
        if phase is None:raise ValueError('Incumbent launches outside current launch/event windows')
        slot=float(row.slot)
        if not math.isfinite(slot) or slot!=int(slot):raise ValueError('Invalid incumbent ship slot')
        schedule.append((int(slot),phase+1,keys[pair],boost,start,end))
    schedule.sort(key=lambda r:(r[4],r[0]))
    validate_schedule([dict(zip(['slot','phase','ship','event_bonus','start_hour','end_hour'],r)) for r in schedule],
                      getattr(args,'max_launches_per_hour',0),args.days*24,dict(zip(available,hours)),args.parallel,event_phases,sleeps,
                      max_total_launches=getattr(args,'max_total_launches',0),max_launches_per_day=getattr(args,'max_launches_per_day',0))
    used=[sum(fuel[available.index(r[2]),k] for r in schedule) for k in range(fuel.shape[1])]
    blocks=[0 if fixed_fuel(args) else int(math.ceil(value/args.fuel_step-1e-9)) for value in used]
    validate_resources(schedule,counts,groups,outputs,inventory,rate,args.event_multiplier,available,fuel,
                       [n*args.fuel_step for n in blocks],args.fuel_step,args.fuel,getattr(args,'fixed_inventory',None))
    return schedule,counts,blocks
