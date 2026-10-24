#!/usr/bin/env python3
"""MILP optimizer for Reggference crafting with multiple 48h launch events.
Events are hypothetical, evenly spaced in the horizon; all rates are expectations.
"""
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import lil_matrix

FUELS=('curiousity','kindness','resilence','integrity')
TARGET='metronome-4'

def load_inventory(path, known_materials):
    """Read actual, whole-item counts separately from probabilistic drops."""
    if path is None:
        return {}
    inventory = {}
    try:
        with Path(path).open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if header is None or sorted(header) != ['material_id', 'quantity']:
                raise ValueError('Inventory CSV must have exactly material_id,quantity columns')
            for row in reader:
                line = reader.line_num
                if len(row) != 2:
                    raise ValueError(f'Inventory CSV line {line}: expected two fields')
                values = dict(zip(header, row))
                material = values['material_id'].strip()
                quantity = values['quantity'].strip()
                if material not in known_materials:
                    raise ValueError(f'Inventory CSV line {line}: unknown material {material!r}')
                if material in inventory:
                    raise ValueError(f'Inventory CSV line {line}: duplicate material {material!r}')
                if not re.fullmatch(r'[0-9]+', quantity):
                    raise ValueError(f'Inventory CSV line {line}: quantity must be a nonnegative integer')
                count = int(quantity)
                if count > 2**53 - 1:
                    raise ValueError(f'Inventory CSV line {line}: quantity exceeds supported maximum {2**53 - 1}')
                inventory[material] = count
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f'Cannot read inventory CSV: {exc}') from exc
    return inventory

def duration_hours(v):
    s=str(v).strip()
    parts=re.findall(r'(\d+(?:\.\d+)?)([dhm])',s)
    if not parts or ''.join(a+b for a,b in parts)!=s: raise ValueError('Bad duration '+repr(v))
    return sum(float(a)*{'d':24,'h':1,'m':1/60}[b] for a,b in parts)

def intervals(days,events,event_hours):
    H=days*24
    if events==0: return [(0.,H,False)]
    if events*event_hours>H: raise ValueError('Events do not fit into horizon')
    # Center hypothetical events around evenly spaced interior points.
    centers=[H*k/(events+1) for k in range(1,events+1)]
    spans=[(c-event_hours/2,c+event_hours/2) for c in centers]
    if spans[0][0]<0 or spans[-1][1]>H or any(spans[i][1]>spans[i+1][0] for i in range(len(spans)-1)):
        raise ValueError('Events overlap or extend beyond planning horizon')
    phases=[]; t=0.
    for a,b in spans:
        if a>t: phases.append((t,a,False))
        phases.append((a,b,True));t=b
    if t<H: phases.append((t,H,False))
    return phases

def sleep_windows(days, daily, absolute):
    """Return sorted, merged [start,end) hours when launches are prohibited."""
    H = days * 24
    windows = []
    def clock(value):
        parts = value.strip().split(':')
        if len(parts) != 2: raise ValueError('Clock must be HH:MM: ' + value)
        hour, minute = (int(x) for x in parts)
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            raise ValueError('Clock out of range: ' + value)
        return hour + minute / 60
    for text in daily:
        try:
            a, b = text.split('-', 1)
            a, b = clock(a), clock(b)
        except (TypeError, ValueError) as e:
            raise ValueError('Invalid --sleep: use HH:MM-HH:MM') from e
        if abs(a-b)<1e-9: raise ValueError('Daily sleep may not be 24 hours')
        if b <= a: b += 24  # overnight
        for day in range(-1, int(np.ceil(days))+1):
            windows.append((day*24+a, day*24+b))
    for text in absolute:
        try:
            a,b = (float(x.strip())*24 for x in text.split('-',1))
        except ValueError as e:
            raise ValueError('Invalid --no-launch: use START_DAY-END_DAY') from e
        if b<=a: raise ValueError('--no-launch requires end after start')
        windows.append((a,b))
    windows = sorted((max(0.,a),min(H,b)) for a,b in windows if b>0 and a<H)
    merged=[]
    for a,b in windows:
        if b<=a: continue
        if merged and a<=merged[-1][1]+1e-8: merged[-1]=(merged[-1][0],max(merged[-1][1],b))
        else: merged.append((a,b))
    return merged

def launch_phases(event_phases, sleeps):
    """Split at event/sleep boundaries; exclude sleeping launch phases."""
    H=event_phases[-1][1]
    points=sorted(set([0.,H]+[v for a,b,_ in event_phases for v in (a,b)]+[v for a,b in sleeps for v in (a,b)]))
    phases=[]
    for a,b in zip(points,points[1:]):
        if b-a<1e-8: continue
        mid=(a+b)/2
        if any(x<=mid<y for x,y in sleeps):continue
        boost=next(boost for x,y,boost in event_phases if x<=mid<y)
        phases.append((a,b,boost))
    if not phases: raise ValueError('No launch windows remain after sleep exclusions')
    return phases

def solve(args):
    target=getattr(args, 'target', TARGET)
    base=Path(args.data_dir)
    if not (base/'mission.csv').exists() and (base/'data'/'mission.csv').exists():base=base/'data'
    mission=pd.read_csv(base/'mission.csv').set_index('ship')
    drops=pd.read_csv(base/args.expectations)
    recipes=pd.read_csv(base/'reggference.csv')
    known_materials=set(recipes.result)|set(recipes.ingredient)|set(drops.material_id)
    inventory=load_inventory(getattr(args, 'inventory', None), known_materials)
    groups=list(recipes.groupby('recipe_id',sort=False))
    outputs={rid:g.result.iloc[0] for rid,g in groups}
    if len(set(outputs.values()))!=len(outputs):raise ValueError('Alternative recipes not supported')
    if any(g.result.nunique()!=1 for _,g in groups):raise ValueError('Invalid recipes')
    available=[s for s in mission.index if s in set(drops.ship)]
    if args.ships:
        requested=set(args.ships.split(','))
        if requested-set(mission.index):raise ValueError('Unknown ships '+str(requested-set(mission.index)))
        available=[s for s in available if s in requested]
    if not available:raise ValueError('No usable ship rates')
    if target not in set(recipes.result):
        raise ValueError(f'Unknown crafting target {target!r}; choose from: '+', '.join(sorted(set(recipes.result))))
    mats={target}
    while True:
        expanded=mats|set(recipes.loc[recipes.result.isin(mats),'ingredient'])
        if expanded==mats:break
        mats=expanded
    groups=[(rid,g) for rid,g in groups if outputs[rid] in mats]
    required_mats=set(mats)
    mats=sorted(mats|set(inventory))
    drops=drops[drops.ship.isin(available)&drops.material_id.isin(mats)].copy()
    numeric_rates=pd.to_numeric(drops.expectation_per_launch,errors='coerce')
    missing_rates=sorted(required_mats-set(drops.loc[numeric_rates.notna(),'material_id']))
    unknown_rates=sorted(set(drops.loc[numeric_rates.isna(),'material_id']))
    if missing_rates:
        print('No known ship drop rates (inventory/crafting only): '+', '.join(missing_rates))
    if unknown_rates:
        print('Unknown drop rates treated as zero (not measured zero): '+', '.join(unknown_rates))
    drops['expectation_per_launch']=pd.to_numeric(drops.expectation_per_launch,errors='coerce').fillna(0)
    if drops.duplicated(['ship','material_id']).any():raise ValueError('Duplicate rates')
    rate={(r.ship,r.material_id):float(r.expectation_per_launch) for r in drops.itertuples()}
    event_phases=intervals(args.days,args.events,args.event_hours)
    sleeps=sleep_windows(args.days,args.sleep,args.no_launch)
    phases=launch_phases(event_phases,sleeps)
    ns=len(available);np_=len(phases);slots=args.parallel
    hours=np.array([duration_hours(mission.loc[s,'duration']) for s in available]);
    fuel=np.array([[float(mission.loc[s,f]) for f in FUELS] for s in available]); fuel_sum=fuel.sum(axis=1)
    # Per slot and phase: count launches per ship, last ship indicator, continuous phase start.
    count_size=slots*np_*ns
    last_size=count_size
    start_size=slots*np_
    rec_size=len(groups)
    fuel_blocks_offset=count_size+last_size+start_size+rec_size
    n=fuel_blocks_offset+len(FUELS)
    def block(k):return fuel_blocks_offset+k
    def count(slot,p,j):return (slot*np_+p)*ns+j
    def last(slot,p,j):return count_size+count(slot,p,j)
    def start(slot,p):return count_size+last_size+slot*np_+p
    recipes_offset=count_size+last_size+start_size
    ridcol={rid:recipes_offset+k for k,(rid,_) in enumerate(groups)}
    rows=[];lbs=[];ubs=[]
    def constraint(coefs,lo=-np.inf,hi=np.inf):
        rows.append(coefs);lbs.append(lo);ubs.append(hi)
    H=args.days*24
    max_h=max(hours)
    max_launches=np.maximum(1,np.floor(H/hours).astype(int)+1)
    phase_cap=[max(1,int(np.ceil((b-a)/min(hours)-1e-10))) for a,b,_ in phases]
    for mat in mats:
        row=defaultdict(float)
        for slot in range(slots):
            for p,(_,_,boost) in enumerate(phases):
                for j,ship in enumerate(available):row[count(slot,p,j)]-=rate.get((ship,mat),0)*(args.event_multiplier if boost else 1)
        for rid,g in groups:
            if outputs[rid]==mat:row[ridcol[rid]]-=1
            for r in g.itertuples():
                if r.ingredient==mat:row[ridcol[rid]]+=float(r.quantity)
        constraint(row,hi=inventory.get(mat,0))
    # Each fuel kind must be provisioned in whole 5T (or --fuel-step) blocks.
    # Individual launches still use their actual fractional-T costs.
    for k,kind in enumerate(FUELS):
        row=defaultdict(float)
        for slot in range(slots):
            for p in range(np_):
                for j in range(ns):row[count(slot,p,j)]+=fuel[j,k]
        row[block(k)]-=args.fuel_step
        constraint(row,hi=0)
    constraint({block(k):1 for k in range(len(FUELS))},hi=int(np.floor(args.fuel/args.fuel_step+1e-9)))
    eps=1/3600
    # All phases occur in order for each ship slot, with idle gaps if needed.
    # last indicators designate which mission starts LAST in that phase.
    # Its completion may cross phase end; subsequent phase starts after completion.
    for slot in range(slots):
        for p,(a,b,boost) in enumerate(phases):
            constraint({start(slot,p):1},lo=a)
            if p>0:
                row=defaultdict(float);row[start(slot,p)]+=1;row[start(slot,p-1)]-=1
                for j in range(ns):row[count(slot,p-1,j)]-=hours[j]
                constraint(row,lo=0)
            row=defaultdict(float)
            for j in range(ns):row[last(slot,p,j)]+=1
            constraint(row,hi=1)
            for j in range(ns):
                constraint({last(slot,p,j):1,count(slot,p,j):-1},hi=0)
            # If launches exist, exactly one last indicator is selected.
            row=defaultdict(float)
            for j in range(ns):
                row[count(slot,p,j)]+=1
                row[last(slot,p,j)]-=phase_cap[p]
            constraint(row,hi=0)
            constraint({count(slot,p,j):1 for j in range(ns)},hi=phase_cap[p])
            # Last launch start <= phase end - 1 second, conditional on nonempty phase
            M=2*H+max_h
            row=defaultdict(float);row[start(slot,p)]+=1
            for j in range(ns):
                row[count(slot,p,j)]+=hours[j]
                row[last(slot,p,j)]+=M-hours[j]
            constraint(row,hi=b-eps+M)
        # End every slot before the horizon.
        row=defaultdict(float);row[start(slot,np_-1)]+=1
        for j in range(ns):row[count(slot,np_-1,j)]+=hours[j]
        constraint(row,hi=H)
    A=lil_matrix((len(rows),n),dtype=float)
    for i,r in enumerate(rows):
        for col,value in r.items():
            if value:A[i,col]=value
    constraints=[LinearConstraint(A.tocsr(),np.array(lbs),np.array(ubs))]
    low=np.zeros(n);up=np.full(n,np.inf)
    for slot in range(slots):
        for p in range(np_):
            up[start(slot,p)]=H
            for j in range(ns):
                up[last(slot,p,j)]=1
                up[count(slot,p,j)]=min(max_launches[j],int(np.ceil((phases[p][1]-phases[p][0])/hours[j]-1e-10)))
    for k in range(len(FUELS)):up[block(k)]=int(np.floor(args.fuel/args.fuel_step+1e-9))
    integrality=np.ones(n);integrality[count_size+last_size:recipes_offset]=0
    goal_rid=next((rid for rid,_ in groups if outputs[rid]==target),None)
    if goal_rid is None:raise ValueError('Missing final crafting recipe')
    obj=np.zeros(n);obj[ridcol[goal_rid]]=-1
    result=milp(obj,integrality=integrality,bounds=Bounds(low,up),constraints=constraints,
                options={'time_limit':args.solver_seconds,'mip_rel_gap':0.0})
    if result.x is None:raise RuntimeError('No feasible solution returned: '+result.message)
    x=result.x
    if np.max(np.abs(x[:count_size+last_size]-np.rint(x[:count_size+last_size])))>1e-4:
        raise RuntimeError('Nonintegral solution returned')
    x[:count_size+last_size]=np.rint(x[:count_size+last_size]);x[recipes_offset:]=np.rint(x[recipes_offset:])
    detail=[];schedule=[]
    for slot in range(slots):
        actual_time=0.
        for p,(a,b,boost) in enumerate(phases):
            counts=[int(x[count(slot,p,j)]) for j in range(ns)]
            end_j=next((j for j in range(ns) if x[last(slot,p,j)]>0.5),None)
            actual_time=max(actual_time,a)
            for j,num in enumerate(counts):
                for z in range(num-(1 if end_j==j else 0)):
                    schedule.append((slot+1,p+1,available[j],boost,actual_time,actual_time+hours[j]))
                    actual_time+=hours[j]
            if end_j is not None:
                schedule.append((slot+1,p+1,available[end_j],boost,actual_time,actual_time+hours[end_j]))
                actual_time+=hours[end_j]
            for j,num in enumerate(counts):
                if num:detail.append({'slot':slot+1,'phase':p+1,'ship':available[j],'event_bonus':boost,'launches':num,
                                       'total_hours':num*hours[j], 'total_fuel_T':num*fuel_sum[j],
                                       **{f+'_T':num*fuel[j,k] for k,f in enumerate(FUELS)}})
    schedule_df=pd.DataFrame(schedule,columns=['slot','phase','ship','event_bonus','start_hour','end_hour'])
    for row in schedule_df.itertuples():
        a,b,boost=phases[row.phase-1]
        if not a-1e-5<=row.start_hour<b+1e-5 or row.end_hour>H+1e-5:
            raise RuntimeError(f'Schedule validation failed: {row}')
    craft=pd.DataFrame([{'material_id':outputs[rid],'crafts':int(x[ridcol[rid]])} for rid,_ in groups if x[ridcol[rid]]>0.5], columns=['material_id','crafts'])
    balance=[]
    for mat in mats:
        source=sum(int(x[count(slot,p,j)])*rate.get((ship,mat),0)*(args.event_multiplier if boost else 1)
                   for slot in range(slots) for p,(_,_,boost) in enumerate(phases) for j,ship in enumerate(available))
        made=sum(int(x[ridcol[rid]]) for rid,g in groups if outputs[rid]==mat)
        used=sum(int(x[ridcol[rid]])*float(r.quantity) for rid,g in groups for r in g.itertuples() if r.ingredient==mat)
        balance.append({'material_id':mat,'expected_drops':source,'crafted':made,'consumed':used,'expected_remaining':inventory.get(mat,0)+source+made-used,'starting_inventory':inventory.get(mat,0)})
    plan=pd.DataFrame(detail, columns=['slot','phase','ship','event_bonus','launches','total_hours','total_fuel_T']+[f+'_T' for f in FUELS]);balance_df=pd.DataFrame(balance)
    print('MILP status:',result.message)
    if result.status!=0:print('WARNING: Solution not certified globally optimal within time limit')
    print(f'Expected {target} crafts: {int(x[ridcol[goal_rid]])}')
    print(f'Already owned {target}: {inventory.get(target,0)}')
    print(f'Total achievable {target}: {inventory.get(target,0)+int(x[ridcol[goal_rid]])}')
    print(f'Fuel used: {plan.total_fuel_T.sum() if len(plan) else 0:.3f} / {args.fuel:g} T')
    fuel_allocation = pd.DataFrame([{'fuel':kind, 'used_T':sum(int(x[count(slot,p,j)])*fuel[j,k]
        for slot in range(slots) for p in range(np_) for j in range(ns)),
        'allocated_T':int(x[block(k)])*args.fuel_step} for k,kind in enumerate(FUELS)])
    fuel_allocation['unused_T']=fuel_allocation.allocated_T-fuel_allocation.used_T
    if (fuel_allocation.unused_T < -1e-5).any():raise RuntimeError('Fuel allocation inconsistent')
    print('Fuel allocation (in blocks of',f'{args.fuel_step:g}T):')
    print(fuel_allocation.to_string(index=False, float_format=lambda v:f'{v:.3f}'))
    print(f'Total allocated: {fuel_allocation.allocated_T.sum():.3f} / {args.fuel:g} T')
    print(f'Simultaneous ships: {args.parallel}; days: {args.days}; hypothetical events: {args.events}')
    for a,b,boost in event_phases:
        if boost:print(f'  Event: days {a/24:g} to {b/24:g}')
    if sleeps:
        print(f'Launch blackouts: {len(sleeps)} window(s)')
    if args.output_dir:
        out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
        (out/'plan_metadata.json').write_text(json.dumps({'target':target,'missing_drop_materials':missing_rates,'unknown_drop_materials':unknown_rates},indent=2)+'\n',encoding='utf-8')
        plan.to_csv(out/'launch_plan.csv',index=False)
        fuel_allocation.to_csv(out/'fuel_allocation.csv',index=False)
        schedule_df.to_csv(out/'schedule.csv',index=False)
        craft.to_csv(out/'craft_plan.csv',index=False)
        balance_df.to_csv(out/'material_balance.csv',index=False)
        pd.DataFrame([{'phase':i+1,'start_hour':a,'end_hour':b,'event_bonus':boost} for i,(a,b,boost) in enumerate(event_phases)]).to_csv(out/'event_windows.csv',index=False)
        pd.DataFrame([{'start_hour':a,'end_hour':b} for a,b in sleeps],columns=['start_hour','end_hour']).to_csv(out/'sleep_windows.csv',index=False)
        print('Output:',out)
        try:
            from build_plan_dashboard import build
            build(out, out / 'plan.html')
        except Exception as exc:
            print('Dashboard not generated:', exc)
    if 'value_note' in drops and drops.value_note.notna().any():print('CAUTION: unknown drop estimates treated as zero')

def main():
    p=argparse.ArgumentParser(description='Optimize Reggference expected crafting across multiple events')
    p.add_argument('--target',default=TARGET,help='Craftable material ID from the recipe CSV')
    p.add_argument('--inventory',type=Path,help='CSV of material_id,quantity starting whole-item counts')
    p.add_argument('--days',type=float,default=30)
    p.add_argument('--fuel',type=float,default=500)
    p.add_argument('--fuel-step',type=float,default=5,help='Each fuel type is allocated in blocks of this many T')
    p.add_argument('--parallel',type=int,default=3)
    p.add_argument('--events',type=int,default=0,help='Number of hypothetical evenly spaced events in horizon')
    p.add_argument('--event-hours',type=float,default=48)
    p.add_argument('--event-multiplier',type=float,default=2)
    p.add_argument('--sleep', action='append', default=[], metavar='HH:MM-HH:MM',
                   help='Daily no-launch interval (repeatable, e.g. --sleep 23:00-08:00)')
    p.add_argument('--no-launch', action='append', default=[], metavar='DAY-DAY',
                   help='One-off no-launch interval in fractional days, e.g. 12.5-13.25')
    p.add_argument('--ships',default=None)
    p.add_argument('--data-dir',default=str(Path(__file__).resolve().parent))
    p.add_argument('--expectations',default='ship_material_expectations.csv')
    p.add_argument('--output-dir',default='results')
    p.add_argument('--solver-seconds',type=float,default=30)
    a=p.parse_args()
    if a.days<=0 or a.fuel<0 or a.fuel_step<=0 or a.parallel<1 or a.events<0 or a.event_hours<=0 or a.event_multiplier<1:p.error('Invalid arguments')
    try:
        solve(a)
    except ValueError as exc:
        p.error(str(exc))
if __name__=='__main__':main()
