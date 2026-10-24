#!/usr/bin/env python3
"""MILP optimizer for Reggference crafting with multiple 48h launch events.
Events are hypothetical, evenly spaced in the horizon; all rates are expectations.
"""
import argparse
import csv
import json
import re
import time
import warnings
from copy import copy
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint
from solver_backend import milp, backend_name
from mission_profiles import load_recipes,expand_profiles,prune_dominated_options
from scipy.sparse import lil_matrix
from schedule_validation import validate_launch_rate, validate_schedule

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

def finite_or_none(value):
    return value if value is None or np.isfinite(value) else None


def run_milp(args, objective, *, label='MILP', seconds=None, maximize=True, objective_name=None, **kwargs):
    seconds=args.solver_seconds if seconds is None else seconds
    deadline=getattr(args,'solver_deadline',None)
    if deadline is not None:seconds=min(seconds,max(.001,deadline-time.perf_counter()))
    print(f'[{label}] Solving: {len(objective)} variables; time limit {seconds:.3f}s',flush=True)
    started=time.perf_counter()
    # SciPy forwards supported HiGHS options not explicitly listed in its wrapper.
    # Tight tolerances keep sub-microhour overlaps out of lexicographic locks.
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='Unrecognized options detected:.*',category=RuntimeWarning)
        result=milp(objective,options={'time_limit':max(0.001,seconds),
                    'mip_rel_gap':0.0,'disp':getattr(args,'verbose_solver',False),
                    'presolve':not (label=='Stage 1 crafts (full model)' and len(objective)>5000),
                    'mip_feasibility_tolerance':1e-9,'primal_feasibility_tolerance':1e-9,
                    'dual_feasibility_tolerance':1e-9},**kwargs)
    elapsed=time.perf_counter()-started
    result.solver_runtime_seconds=elapsed
    if hasattr(args,'solver_runs'):
        args.solver_runs.append({'stage':label,'runtime_seconds':elapsed,'status':getattr(result,'status',None),
                                'objective':finite_or_none(getattr(result,'fun',None)),'bound':finite_or_none(getattr(result,'mip_dual_bound',None)),'gap':finite_or_none(getattr(result,'mip_gap',None))})
    print(f'[{label}] Finished in {elapsed:.3f}s (overall {time.perf_counter()-getattr(args,"optimization_started",started):.3f}s): status {result.status if hasattr(result,"status") else "unknown"}, {result.message}',flush=True)
    feasible=getattr(result,'fun',None)
    gap=getattr(result,'mip_gap',None)
    bound=getattr(result,'mip_dual_bound',None)
    print(f'[{label}] Best feasible objective ({objective_name or ("maximize crafts" if maximize else "minimize launches")}): {(-feasible if maximize else feasible) if feasible is not None else "none"}; '
          f'bound: {(-bound if maximize else bound) if bound is not None else "unavailable"}; '
          f'gap: {gap if gap is not None else "unavailable"}',flush=True)
    return result


def polish_model(args, incumbent, matrix, lbs, ubs, low, up, integrality, goal, objectives, scope, validate=None):
    """Fix crafts, lock attained values, and label conditional versus proven minima."""
    from scipy.sparse import vstack, csr_matrix
    budget=getattr(args,'polish_seconds',10.)
    stages=[]
    if budget<=0:return incumbent,stages
    stage_args=copy(args)
    if hasattr(stage_args,'solver_deadline'):del stage_args.solver_deadline
    deadline=min(time.perf_counter()+budget,getattr(args,'polish_deadline',float('inf')))
    stage_args.solver_deadline=deadline
    lo=np.array(low,copy=True);hi=np.array(up,copy=True)
    lo[goal]=hi[goal]=round(incumbent[goal])
    x=incumbent.copy()
    for number,(name,objective) in enumerate(objectives):
        remaining=deadline-time.perf_counter()
        if remaining<=.001:break
        # Keep the current incumbent feasible and forbid worsening this priority.
        bound=float(objective@x)
        row=csr_matrix(objective.reshape(1,-1))
        candidate_matrix=vstack([matrix,row],format='csr')
        candidate_lbs=np.r_[lbs,-np.inf];candidate_ubs=np.r_[ubs,bound+1e-7]
        weights={'fuel allocation':.4,'mission completion time':.5,'earlier launches':.08,'earlier launch phases':.08,'mission count':.02}
        pending=sum(weights.get(item[0],1.) for item in objectives[number:])
        stage_args.solver_seconds=remaining*weights.get(name,1.)/pending
        result=run_milp(stage_args,objective,label='Secondary: '+name,maximize=False,objective_name=name,
                        integrality=integrality,bounds=Bounds(lo,hi),incumbent=x,
                        constraints=LinearConstraint(candidate_matrix,candidate_lbs,candidate_ubs))
        accepted=False
        if result.x is not None:
            proposal=result.x
            residual=matrix@proposal
            feasible=(np.all(residual>=np.asarray(lbs)-1e-5) and np.all(residual<=np.asarray(ubs)+1e-5)
                      and abs(proposal[goal]-lo[goal])<1e-5 and float(objective@proposal)<=bound+1e-6)
            if feasible and validate is not None:
                try:validate(proposal)
                except ValueError:feasible=False
            if feasible:x=proposal.copy();accepted=True
        stages.append({'objective':name,'status':int(result.status),'accepted':accepted,
                       'value':float(objective@x),'scope':scope,'bound':finite_or_none(getattr(result,'mip_dual_bound',None)),
                       'gap':finite_or_none(getattr(result,'mip_gap',None)),'proven_in_scope':bool(result.status==0 and accepted),
                       'fixed_craft_count':int(lo[goal]),
                       'higher_priority_locks':[{'objective':prior['objective'],'value':prior['value'],'proven_in_scope':prior['proven_in_scope']} for prior in stages]})
        if not accepted and result.x is not None:
            print('[Secondary] Invalid numerical candidate rejected; retaining the prior feasible plan',flush=True)
        if result.status!=0 or not accepted:
            print('[Secondary] Minimum not proven; locking the best feasible value for conditional lower-priority improvement',flush=True)
        # Integer objectives may be locked exactly. Continuous objectives allow
        # only a small numerical tolerance, never a weighted objective tradeoff.
        matrix=candidate_matrix;lbs=candidate_lbs;ubs=np.r_[ubs,float(objective@x)+1e-7]
    return x,stages


def compact_fixed_schedule(args, schedule, phases):
    """Exact least-solution algorithm for a fixed-order temporal model.

    Variables are mission start times. Bounds are the UNION of all awake phases
    with the same multiplier, not the original phase. Precedence, duration and
    per-slot rolling-rate edges are lower bounds. Forward propagation into the
    earliest allowed phase gives the componentwise least feasible solution:
    induction on each slot proves makespan and total start time optimal for
    these fixed identities/orders. It is not a proof over other mission orders.
    """
    if not schedule or getattr(args,'polish_seconds',10.)<=0:return schedule,[]
    limit=getattr(args,'max_launches_per_hour',0);H=args.days*24
    result=[];history={};finish={}
    for row in sorted(schedule,key=lambda r:(r[4],r[0])):
        slot,p,ship,boost,old_start,old_end=row
        duration=old_end-old_start
        starts=history.setdefault(slot,[])
        earliest=finish.get(slot,0.)
        if limit and len(starts)>=limit:earliest=max(earliest,starts[-limit]+1.)
        selected=None
        for phase,(a,b,bonus) in enumerate(phases):
            t=max(a,earliest)
            if bonus==boost and t<=b-1/3600+1e-9 and t+duration<=H+1e-9:
                selected=(phase,t);break
        if selected is None:raise ValueError('Fixed-order timing model has no feasible calendar assignment')
        phase,t=selected
        if t>old_start+1e-7:raise ValueError('Calendar solver contradicted its existing feasible schedule')
        starts.append(t);finish[slot]=t+duration
        result.append((slot,phase+1,ship,boost,t,t+duration))
    result.sort(key=lambda r:(r[4],r[0]))
    records=[dict(zip(['slot','phase','ship','event_bonus','start_hour','end_hour'],r)) for r in result]
    validate_schedule(records,limit,H,max_slots=getattr(args,'parallel',None),event_windows=phases)
    scope='fixed mission identities, event multipliers, slots and per-slot order; all eligible calendar phases'
    completion=max(row[5] for row in result);earlier=sum(row[4] for row in result)
    print(f'[Calendar timing] Fixed-order optimum: completion day {completion/24:.4f}; launch identities and fuel unchanged',flush=True)
    return result,[{'objective':name,'status':0,'accepted':True,'value':value,'scope':scope,'proven_in_scope':True,'bound':value,'gap':0.}
                   for name,value in [('fixed-plan completion time',completion),('fixed-plan earlier launches',earlier)]]


def solve_timed_launches(args, available, hours, fuel, phases, mats, groups, outputs, inventory, rate, target, launch_cap=None, target_upper=None):
    """Continuous-time MILP with globally ordered, optional individual launches.

    Each slot tracks the last L launch times; its next launch must be at
    least one hour after its L-th preceding launch. Other slots are independent.
    Each launch selects one ship/phase and one slot. Per-slot ready times
    carry forward across ALL launches, including those assigned elsewhere.
    No rounding, shifting, or schedule repair is performed after solving.
    """
    from scipy.sparse import coo_matrix
    H = args.days * 24
    limit = args.max_launches_per_hour
    # Two independent safe bounds on the number of completed missions.
    nlaunch = min(int(np.ceil(H) * limit * args.parallel), int(args.parallel * np.floor(H / min(hours))))
    minimum_fuel=float(np.min(fuel.sum(axis=1)))
    if minimum_fuel>0:
        nlaunch=min(nlaunch,int(np.floor(args.fuel/minimum_fuel+1e-9)))
    safe_cap=nlaunch
    if launch_cap is not None:nlaunch=min(nlaunch,launch_cap)
    print(f'[Schedule] Constructing continuous-time model: {nlaunch} launches (full safe bound {safe_cap})',flush=True)
    construction_started=time.perf_counter()
    boosts=sorted(set(boost for _,_,boost in phases))
    choices=[(boost,j) for boost in boosts for j,h in enumerate(hours) if h<=H]
    lower=[]; upper=[]; integer=[]
    def var(lo=0, hi=np.inf, discrete=False):
        idx=len(lower);lower.append(lo);upper.append(hi);integer.append(int(discrete));return idx
    times=[var(hi=H) for _ in range(nlaunch)]
    ready=[[var(hi=H) for _ in range(args.parallel)] for _ in range(nlaunch)]
    slots=[[var(hi=1,discrete=True) for _ in range(args.parallel)] for _ in range(nlaunch)]
    choices_by_launch=[{(p,j):var(hi=1,discrete=True) for p,j in choices} for _ in range(nlaunch)]
    phase_choices=[{p:var(hi=1,discrete=True) for p in range(len(phases))} for _ in range(nlaunch)]
    # If L missions cannot finish within an hour, nonoverlap already enforces
    # the rolling rule. Otherwise track each slot's last L launch+1h thresholds.
    needs_history=bool(limit and min(hours)*limit<1-1e-12)
    history=[[[var(hi=H+1) for _ in range(limit)] for _ in range(args.parallel)]
             for _ in range(nlaunch)] if needs_history else None
    crafts={rid:var(discrete=True) for rid,_ in groups}
    makespan=var(hi=H)
    active_times=[var(hi=H) for _ in range(nlaunch)]
    blocks=[var(hi=int(np.floor(args.fuel/args.fuel_step+1e-9)),discrete=True) for _ in FUELS]
    ri=[];ci=[];values=[];lbs=[];ubs=[]
    def constraint(row,lo=-np.inf,hi=np.inf):
        index=len(lbs);lbs.append(lo);ubs.append(hi)
        for col,value in row.items():
            if value:ri.append(index);ci.append(col);values.append(value)
    def active(i,scale=1):
        return {col:scale for col in choices_by_launch[i].values()}
    M=H+max(hours)+1
    for i,choices_i in enumerate(choices_by_launch):
        constraint(active(i),hi=1)
        row=active(i,-1)
        row.update({col:1 for col in slots[i]})
        constraint(row,lo=0,hi=0)
        row=active(i,-1);row.update({col:1 for col in phase_choices[i].values()})
        constraint(row,lo=0,hi=0)
        for boost in boosts:
            row={col:1 for (b,j),col in choices_i.items() if b==boost}
            row.update({col:-1 for p,col in phase_choices[i].items() if phases[p][2]==boost})
            constraint(row,lo=0,hi=0)
        if i:
            row=active(i);row.update(active(i-1,-1));constraint(row,hi=0)
            constraint({times[i]:1,times[i-1]:-1},lo=0)
        for p,(a,b,_) in enumerate(phases):
            cols=[phase_choices[i][p]]
            if not cols:continue
            # Match the existing model's one-second guard before phase ends.
            row={col:-M for col in cols};row[times[i]]=1
            constraint(row,lo=a-M)
            row={col:M for col in cols};row[times[i]]=1
            constraint(row,hi=min(b-1/3600,H)+M)
        row=active(i,-H);row[active_times[i]]=1;constraint(row,hi=0)
        constraint({active_times[i]:1,times[i]:-1},hi=0)
        row=active(i,-H);row.update({active_times[i]:1,times[i]:-1});constraint(row,lo=-H)
        duration={col:hours[j] for (p,j),col in choices_i.items()}
        row=dict(duration);row[times[i]]=1
        constraint(row,hi=H)
        row=active(i,-H);row.update({makespan:1,times[i]:-1})
        for col,h in duration.items():row[col]-=h
        constraint(row,lo=-H)
        for slot,u in enumerate(slots[i]):
            if history is not None:
                if i:
                    constraint({times[i]:1,history[i-1][slot][-1]:-1,u:-M},lo=-M)
                for k,q in enumerate(history[i][slot]):
                    if i:
                        # Preserve the queue if this launch belongs elsewhere.
                        constraint({q:1,history[i-1][slot][k]:-1,u:M},lo=0)
                    if k==0:
                        constraint({q:1,times[i]:-1,u:-M},lo=1-M)
                    elif i:
                        # Shift history on a launch in this slot only.
                        constraint({q:1,history[i-1][slot][k-1]:-1,u:-M},lo=-M)
            if i:
                constraint({ready[i][slot]:1,ready[i-1][slot]:-1},lo=0)
                constraint({times[i]:1,ready[i-1][slot]:-1,u:-M},lo=-M)
            row={ready[i][slot]:1,times[i]:-1,u:-M}
            row.update({col:-h for col,h in duration.items()})
            constraint(row,lo=-M)
    for mat in mats:
        row=defaultdict(float)
        for choices_i in choices_by_launch:
            for (p,j),col in choices_i.items():
                row[col]-=rate.get((available[j],mat),0)*(args.event_multiplier if p else 1)
        for rid,g in groups:
            if outputs[rid]==mat:row[crafts[rid]]-=1
            for r in g.itertuples():
                if r.ingredient==mat:row[crafts[rid]]+=float(r.quantity)
        constraint(row,hi=inventory.get(mat,0))
    for k in range(len(FUELS)):
        row={blocks[k]:-args.fuel_step}
        for choices_i in choices_by_launch:
            row.update({col:fuel[j,k] for (p,j),col in choices_i.items()})
        constraint(row,hi=0)
    constraint({col:1 for col in blocks},hi=int(np.floor(args.fuel/args.fuel_step+1e-9)))
    objective=np.zeros(len(lower))
    goal=next(rid for rid,_ in groups if outputs[rid]==target)
    objective[crafts[goal]]=-1
    if target_upper is not None:upper[crafts[goal]]=target_upper
    matrix=coo_matrix((values,(ri,ci)),shape=(len(lbs),len(lower))).tocsr()
    print(f'[Schedule] Constructed in {time.perf_counter()-construction_started:.3f}s: '
          f'{len(lower)} variables ({sum(integer)} integer), {len(lbs)} constraints, {matrix.nnz} nonzeros',flush=True)
    if launch_cap is not None and nlaunch<safe_cap:
        print('[Schedule] Solving a launch-capped subproblem; its local optimum is not a global proof',flush=True)
    result=run_milp(args,objective,label='Schedule',integrality=np.array(integer),bounds=Bounds(lower,upper),
                constraints=LinearConstraint(matrix,lbs,ubs))
    result.full_launch_bound=safe_cap
    result.launch_cap=nlaunch
    if result.x is None:
        if nlaunch==0 and getattr(result,'status',None)==1:
            result.x=np.zeros(len(lower));result.fun=0.0
            result.message='Time limit; explicit zero-launch seed (zero new crafts)'
        else:
            raise RuntimeError('No feasible solution returned: '+result.message)
    x=result.x
    discrete=np.array(integer,dtype=bool)
    if (np.abs(x[discrete]-np.rint(x[discrete]))>1e-4).any():
        raise RuntimeError('Nonintegral solution returned')
    def extract(x):
        schedule=[]
        for i,choices_i in enumerate(choices_by_launch):
            selected=[(p,j) for (p,j),col in choices_i.items() if x[col]>0.5]
            if not selected:continue
            boost,j=selected[0]
            p=next(p for p,col in phase_choices[i].items() if x[col]>0.5)
            slot=next(k for k,col in enumerate(slots[i]) if x[col]>0.5)
            t=float(x[times[i]])
            schedule.append((slot+1,p+1,available[j],phases[p][2],t,t+hours[j]))
        validate_schedule([dict(zip(['slot','phase','ship','event_bonus','start_hour','end_hour'],r)) for r in schedule],limit)
        return schedule, {rid:int(round(x[col])) for rid,col in crafts.items()}, [int(round(x[col])) for col in blocks]
    def validate_timed(proposal):
        rows=extract(proposal)[0]
        records=[dict(zip(['slot','phase','ship','event_bonus','start_hour','end_hour'],row)) for row in rows]
        validate_schedule(records,limit,H,dict(zip(available,hours)),args.parallel,phases)
    def polish(deadline=None):
        polish_args=copy(args)
        if deadline is not None:polish_args.polish_deadline=deadline
        allocation=np.zeros(len(lower));allocation[blocks]=args.fuel_step
        count_obj=np.zeros(len(lower))
        for choices_i in choices_by_launch:
            for (boost,j),col in choices_i.items():count_obj[col]=1
        completion=np.zeros(len(lower));completion[makespan]=1
        earlier=np.zeros(len(lower));earlier[active_times]=1
        improved,stages=polish_model(polish_args,result.x,matrix,np.array(lbs),np.array(ubs),lower,upper,np.array(integer),crafts[goal],
                    [('fuel allocation',allocation),('mission completion time',completion),
                     ('earlier launches',earlier),('mission count',count_obj)],('full continuous timed model' if nlaunch==safe_cap else f'continuous timed model, launch cap {nlaunch} (safe bound {safe_cap})'),validate=validate_timed)
        result.secondary_stages=stages
        return extract(improved)
    result.polish_schedule=polish
    schedule,craft_counts,fuel_blocks=extract(x)
    return result,schedule,craft_counts,fuel_blocks



def remove_surplus_missions(schedule, craft_counts, groups, outputs, inventory, rate, multiplier, target):
    """Remove only provably surplus work; never change remaining launch times."""
    balance=defaultdict(float,inventory)
    for rid,g in groups:
        quantity=craft_counts[rid];balance[outputs[rid]]+=quantity
        for r in g.itertuples():balance[r.ingredient]-=quantity*float(r.quantity)
    for row in schedule:
        ship,boost=row[2],row[3]
        for (source,mat),value in rate.items():
            if source==ship:balance[mat]+=value*(multiplier if boost else 1)
    removed_crafts=0
    while True:
        changed=False
        for rid,g in groups:
            out=outputs[rid]
            if out==target:continue
            amount=min(craft_counts[rid],max(0,int(np.floor(balance[out]+1e-7))))
            if amount:
                craft_counts[rid]-=amount;balance[out]-=amount;removed_crafts+=amount;changed=True
                for r in g.itertuples():balance[r.ingredient]+=amount*float(r.quantity)
        if not changed:break
    kept=[];removed=[]
    for row in sorted(schedule,key=lambda r:r[5],reverse=True):
        contribution={mat:value*(multiplier if row[3] else 1) for (ship,mat),value in rate.items() if ship==row[2]}
        if all(balance[mat]-value>=-1e-7 for mat,value in contribution.items()):
            removed.append(row)
            for mat,value in contribution.items():balance[mat]-=value
        else:kept.append(row)
    return sorted(kept,key=lambda r:(r[4],r[0])),len(removed),removed_crafts


def validate_resources(schedule, craft_counts, groups, outputs, inventory, rate, multiplier, available, fuel, allocation, step, budget):
    """Recompute resources independently from the actual exported missions."""
    material=defaultdict(float,inventory)
    for rid,g in groups:
        material[outputs[rid]]+=craft_counts[rid]
        for r in g.itertuples():material[r.ingredient]-=craft_counts[rid]*float(r.quantity)
    used=np.zeros(len(FUELS))
    for row in schedule:
        used+=fuel[available.index(row[2])]
        for (ship,mat),value in rate.items():
            if ship==row[2]:material[mat]+=value*(multiplier if row[3] else 1)
    allocation=np.asarray(allocation,dtype=float)
    if not np.isfinite(allocation).all() or (allocation<-1e-7).any() or (used>allocation+1e-7).any() or allocation.sum()>budget+1e-7:
        raise ValueError('Independent validation failed: fuel allocation/consumption')
    if (np.abs(allocation/step-np.rint(allocation/step))>1e-7).any():raise ValueError('Independent validation failed: fuel increments')
    if any(value<-1e-7 for value in material.values()):raise ValueError('Independent validation failed: negative material balance')
    return material,used


def objective_guarantees(result, craft_count, allocated, completion):
    """A local/capped optimum is never presented as a global certificate."""
    stages=getattr(result,'secondary_stages',[])
    def stage(name,value):
        selected=next((s for s in stages if s['objective']==name),None)
        if selected is None:return {'proven':False,'value':value,'scope':'not solved'}
        scope=selected['scope']
        unrestricted=scope in ['exact aggregate model','full continuous timed model']
        return {'proven':bool(selected.get('proven_in_scope') and unrestricted and abs(selected['value']-value)<1e-5),
                'value':value,'bound':selected.get('bound'),'gap':selected.get('gap'),'scope':scope,
                'proven_in_scope':selected.get('proven_in_scope',False)}
    fuel=stage('fuel allocation',allocated)
    fuel['fixed_craft_count']=craft_count
    if allocated==0:
        fuel.update(proven=True,bound=0.,gap=0.,scope='nonnegative fuel lower bound attained by feasible plan')
    finish=stage('mission completion time',completion)
    finish['conditional_proven']=finish['proven']
    finish['proven']=finish['proven'] and fuel['proven']
    return {'crafts':{'proven':result.status==0,'value':craft_count,'bound':getattr(result,'upper_bound_crafts',None),
                      'gap':finite_or_none(getattr(result,'mip_gap',None))},
            'allocated_fuel':fuel,'completion':finish}


def solve(args):
    print('[Setup] Reading inputs and constructing model; '+backend_name(),flush=True)
    model_started=time.perf_counter()
    args.optimization_started=model_started
    args.solver_runs=[]
    target=getattr(args, 'target', TARGET)
    base=Path(args.data_dir)
    if not (base/'mission.csv').exists() and (base/'data'/'mission.csv').exists():base=base/'data'
    mission=pd.read_csv(base/'mission.csv').set_index('ship')
    drops=pd.read_csv(base/args.expectations)
    recipes=load_recipes(base)
    if args.ships:
        requested=set(args.ships.split(','))
        if requested-set(mission.index):raise ValueError('Unknown ships '+str(requested-set(mission.index)))
        mission=mission.loc[[ship for ship in mission.index if ship in requested]]
    mission,drops,profile_info=expand_profiles(mission,drops,base/args.expectations)
    if profile_info['recipe_warnings']:
        print('[Recipes] Supplied definitions differ from pinned wasmegg recipes; preserved as configured. See drop_profile_source.recipe_warnings in plan metadata.',flush=True)
    known_materials=set(recipes.result)|set(recipes.ingredient)|set(drops.material_id)
    inventory=load_inventory(getattr(args, 'inventory', None), known_materials)
    groups=list(recipes.groupby('recipe_id',sort=False))
    outputs={rid:g.result.iloc[0] for rid,g in groups}
    if len(set(outputs.values()))!=len(outputs):raise ValueError('Alternative recipes not supported')
    if any(g.result.nunique()!=1 for _,g in groups):raise ValueError('Invalid recipes')
    available=[s for s in mission.index if s in set(drops.ship)]
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
    consumed_materials=set(recipes.loc[recipes.result.isin(mats),'ingredient'])
    original_options=len(available)
    available=prune_dominated_options(available,mission,drops,consumed_materials)
    print(f'[Profiles] {len(available)} useful nondominated mission options from {original_options}; unknown supply is uncredited',flush=True)
    mats=sorted(mats|set(inventory))
    drops=drops[drops.ship.isin(available)&drops.material_id.isin(mats)].copy()
    numeric_rates=pd.to_numeric(drops.expectation_per_launch,errors='coerce')
    missing_rates=sorted(required_mats-set(drops.loc[numeric_rates.notna(),'material_id']))
    unknown_rates=sorted(set(drops.loc[numeric_rates.isna(),'material_id']))
    if missing_rates:
        print('No known ship drop rates (inventory/crafting only): '+', '.join(missing_rates))
    if unknown_rates:
        print('Unknown drop rates omitted from modeled supply (not measured zero): '+', '.join(unknown_rates))
    drops['expectation_per_launch']=pd.to_numeric(drops.expectation_per_launch,errors='coerce').fillna(0)
    if drops.duplicated(['ship','material_id']).any():raise ValueError('Duplicate rates')
    rate={(r.ship,r.material_id):float(r.expectation_per_launch) for r in drops.itertuples()}
    event_phases=intervals(args.days,args.events,args.event_hours)
    sleeps=sleep_windows(args.days,args.sleep,args.no_launch)
    phases=launch_phases(event_phases,sleeps)
    ns=len(available);np_=len(phases);slots=args.parallel
    hours=np.array([duration_hours(mission.loc[s,'duration']) for s in available]);
    try:fuel=np.array([[float(mission.loc[s,f]) for f in FUELS] for s in available])
    except (KeyError,TypeError,ValueError) as exc:raise ValueError('Mission fuel columns require explicit numeric values; missing fuel is not zero') from exc
    if not np.isfinite(fuel).all() or (fuel<0).any():
        raise ValueError('Mission fuel values must be explicit finite nonnegative numbers; missing fuel is not zero')
    if not np.isfinite(hours).all() or (hours<=0).any():raise ValueError('Mission durations must be finite and positive')
    fuel_sum=fuel.sum(axis=1)
    zero_fuel_ships=sorted({mission.loc[ship,'base_ship'] for ship,total in zip(available,fuel_sum) if total==0})
    if zero_fuel_ships:print('[Inputs] Explicit zero fuel in mission.csv: '+', '.join(zero_fuel_ships),flush=True)
    launch_limit=getattr(args,'max_launches_per_hour',0)
    needs_timed=bool(launch_limit and min(hours)*launch_limit<1)
    if launch_limit and not needs_timed:
        print('[Model] Per-slot rate is implied by mission durations and nonoverlap; using exact aggregate model',flush=True)
    # Per slot and phase: count launches per ship, last ship indicator, continuous phase start.
    count_size=slots*np_*ns
    last_size=count_size
    start_size=slots*np_
    rec_size=len(groups)
    fuel_blocks_offset=count_size+last_size+start_size+rec_size
    n=fuel_blocks_offset+len(FUELS)+1
    makespan=n-1
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
            M=max(0.,H-b+eps) # Empty phase only needs start <= H, not 2H + max duration.
            row=defaultdict(float);row[start(slot,p)]+=1
            for j in range(ns):
                row[count(slot,p,j)]+=hours[j]
                row[last(slot,p,j)]+=M-hours[j]
            constraint(row,hi=b-eps+M)
        # Completion time only depends on nonempty phases, not later empty days.
        for p in range(np_):
            row={makespan:1,start(slot,p):-1}
            for j in range(ns):row[count(slot,p,j)]=-hours[j];row[last(slot,p,j)]=-H
            constraint(row,lo=-H)
            # A valid activation/work bound avoids relaxing completion by H
            # when an active phase indicator is fractional.
            row={makespan:1}
            for j in range(ns):row[count(slot,p,j)]=-hours[j];row[last(slot,p,j)]=-phases[p][0]
            constraint(row,lo=0)
        row={makespan:1}
        for p in range(np_):
            for j in range(ns):row[count(slot,p,j)]=-hours[j]
        constraint(row,lo=0)
        # End every slot before the horizon.
        row=defaultdict(float);row[start(slot,np_-1)]+=1
        for j in range(ns):row[count(slot,np_-1,j)]+=hours[j]
        constraint(row,hi=H)
    for slot in range(slots-1):
        row={count(slot,p,j):1 for p in range(np_) for j in range(ns)}
        row.update({count(slot+1,p,j):-1 for p in range(np_) for j in range(ns)})
        constraint(row,lo=0)
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
                if fuel_sum[j]>0:up[count(slot,p,j)]=min(up[count(slot,p,j)],int(np.floor(args.fuel/fuel_sum[j]+1e-9)))
    for k in range(len(FUELS)):up[block(k)]=int(np.floor(args.fuel/args.fuel_step+1e-9))
    up[makespan]=H
    integrality=np.ones(n);integrality[count_size+last_size:recipes_offset]=0;integrality[makespan]=0
    goal_rid=next((rid for rid,_ in groups if outputs[rid]==target),None)
    if goal_rid is None:raise ValueError('Missing final crafting recipe')
    obj=np.zeros(n);obj[ridcol[goal_rid]]=-1
    launch_limit=getattr(args,'max_launches_per_hour',0)
    if launch_limit < 0:
        raise ValueError('Maximum launches per hour must be a nonnegative integer')
    print(f'[Aggregate] Constructed in {time.perf_counter()-model_started:.3f}s: {n} variables, {len(rows)} constraints',flush=True)
    if needs_timed:
        # The unlimited scheduling model is a relaxation of the rate-limited
        # problem. Its dual bound bounds crafts, NEVER proves a schedule valid.
        solve_started=time.perf_counter()
        relaxation=run_milp(args,obj,label='Craft upper bound',seconds=min(5.,args.solver_seconds*0.2),
                            integrality=np.zeros(n),bounds=Bounds(low,up),constraints=constraints)
        bound=getattr(relaxation,'mip_dual_bound',None)
        if relaxation.status==0:bound=relaxation.fun
        target_upper=int(np.floor(-bound+1e-6)) if bound is not None and np.isfinite(bound) else None
        initial_cap=None
        if relaxation.x is not None:
            initial_cap=int(np.ceil(sum(relaxation.x[:count_size])-1e-7))
            # Remove surplus launches in a second small aggregate solve.
            remaining=args.solver_seconds-(time.perf_counter()-solve_started)
            if remaining>0.01:
                compact_obj=np.zeros(n);compact_obj[:count_size]=1
                fixed_low=low.copy();fixed_up=up.copy()
                fixed_low[ridcol[goal_rid]]=fixed_up[ridcol[goal_rid]]=int(np.floor(relaxation.x[ridcol[goal_rid]]+1e-6))
                compact=run_milp(args,compact_obj,label='Compact launch plan',maximize=False,seconds=min(2.,remaining*0.15),
                                 integrality=np.zeros(n),bounds=Bounds(fixed_low,fixed_up),constraints=constraints,
                                 )
                if compact.x is not None:initial_cap=int(np.ceil(sum(compact.x[:count_size])-1e-7))
        seed_args=copy(args)
        seed_args.solver_seconds=min(.2,args.solver_seconds*.05)
        seed_args.solver_deadline=solve_started+args.solver_seconds
        seed=solve_timed_launches(seed_args,available,hours,fuel,phases,mats,groups,outputs,inventory,rate,target,launch_cap=0,target_upper=target_upper)
        best=seed
        cap=min(initial_cap,32) if initial_cap is not None else 32
        while True:
            remaining=args.solver_seconds-(time.perf_counter()-solve_started)
            if remaining<=0:break
            stage_args=copy(args)
            stage_args.solver_deadline=solve_started+args.solver_seconds
            # Reserve time for refinement if a launch-capped model cannot
            # attain the proven upper bound. Unfinished solves are NOT cuts.
            stage_args.solver_seconds=max(.001,remaining*0.65 if cap is not None else remaining)
            try:
                candidate=solve_timed_launches(stage_args,available,hours,fuel,phases,mats,groups,outputs,
                                               inventory,rate,target,launch_cap=cap,target_upper=target_upper)
            except RuntimeError as exc:
                if not str(exc).startswith('No feasible solution returned:'):raise
                print(f'[Refine] {exc}; expanding launch capacity',flush=True)
                candidate=None
            if candidate is not None:
                if best is None or candidate[2][goal_rid]>best[2][goal_rid]:best=candidate
                candidate_result=candidate[0]
                if target_upper is not None and best[2][goal_rid]>=target_upper:
                    best[0]['status']=0
                    best[0]['message']='Optimal: valid schedule attains the aggregate relaxation upper bound'
                    best[0]['mip_gap']=0.0
                    break
                if candidate_result['launch_cap']==candidate_result['full_launch_bound']:
                    full_bound=getattr(candidate_result,'mip_dual_bound',None)
                    if full_bound is not None and np.isfinite(full_bound):
                        proven=int(np.floor(-full_bound+1e-6))
                        target_upper=proven if target_upper is None else min(target_upper,proven)
                    if target_upper is not None and best[2][goal_rid]>=target_upper:
                        best[0]['status']=0;best[0]['message']='Optimal: valid schedule meets proven upper bound';best[0]['mip_gap']=0.0
                    break
                cap=min(candidate_result['full_launch_bound'],max(candidate_result['launch_cap']+1,candidate_result['launch_cap']*2))
            else:
                # Expand toward the full exact model; never exclude a count plan
                # merely because a scheduling attempt timed out.
                if cap is None:break
                cap=max(1,cap*2)
                if cap>=int(np.ceil(H)*launch_limit*slots):cap=None
            print(f'[Refine] Retrying with launch cap {cap if cap is not None else "full"}',flush=True)
        if best is None:raise RuntimeError('No feasible timed schedule found within solver budget; no plan exported')
        result,schedule,craft_counts,fuel_blocks=best
        achieved=craft_counts[goal_rid]
        if not (target_upper is not None and achieved>=target_upper):
            if result['launch_cap']<result['full_launch_bound']:
                result['status']=1
                result['message']='Feasible schedule; global optimality not proven (restricted launch model)'
            if target_upper is not None:
                result['mip_gap']=(target_upper-achieved)/abs(achieved) if achieved else (0. if target_upper==0 else None)
        result['upper_bound_crafts']=target_upper
        result['total_optimization_seconds']=time.perf_counter()-solve_started
        print(f'[Two-stage] Total optimization wall time: {result["total_optimization_seconds"]:.3f}s; '
              f'feasible crafts {achieved}; upper bound {target_upper}; gap {getattr(result,"mip_gap",None)}; {result.message}',flush=True)
        args.polish_deadline=time.perf_counter()+getattr(args,'polish_seconds',10.)
        if hasattr(result,'polish_schedule'):
            schedule,craft_counts,fuel_blocks=result.polish_schedule(args.polish_deadline)
        x=np.zeros(n)
        for slot,p,ship,boost,t,end in schedule:
            x[count(slot-1,p-1,available.index(ship))]+=1
        for rid,value in craft_counts.items():x[ridcol[rid]]=value
        for k,value in enumerate(fuel_blocks):x[block(k)]=value
        detail=[]
        for slot in range(slots):
            for p,(_,_,boost) in enumerate(phases):
                for j,ship in enumerate(available):
                    num=int(x[count(slot,p,j)])
                    if num:detail.append({'slot':slot+1,'phase':p+1,'ship':ship,'event_bonus':boost,'launches':num,
                        'total_hours':num*hours[j],'total_fuel_T':num*fuel_sum[j],
                        **{f+'_T':num*fuel[j,k] for k,f in enumerate(FUELS)}})
    else:
        # A small restriction supplies an incumbent, not a craft upper bound.
        # Leave most sleep phases empty initially; the full model can use them.
        primary_started=time.perf_counter()
        zero=np.zeros(n)
        for slot in range(slots):
            for p,(a,b,boost) in enumerate(phases):zero[start(slot,p)]=a
        seed_up=up.copy()
        important={0}|{p for p,(_,_,boost) in enumerate(phases) if boost}
        for p in list(important):
            if p+1<np_:important.add(p+1)
        for slot in range(slots):
            for p in range(np_):
                if p not in important:
                    for j in range(ns):seed_up[count(slot,p,j)]=seed_up[last(slot,p,j)]=0
        seed=run_milp(args,obj,label='Stage 1 seed (restricted phases)',seconds=min(2.,args.solver_seconds*.2),
                      integrality=integrality,bounds=Bounds(low,seed_up),constraints=constraints,incumbent=zero)
        incumbent=seed.x if seed.x is not None else zero
        result=run_milp(args,obj,label='Stage 1 crafts (full model)',seconds=max(.001,args.solver_seconds-(time.perf_counter()-primary_started)),
                        integrality=integrality,bounds=Bounds(low,up),constraints=constraints,incumbent=incumbent)
        if result.status in [2,3,4]:raise RuntimeError('Full model failed: '+result.message)
        if result.x is None or float(obj@incumbent)<result.fun-1e-7:
            if result.x is not None and result.status==0:raise RuntimeError('Full solver optimum contradicts known feasible incumbent')
            result.x=incumbent.copy();result.fun=float(obj@incumbent)
            result.status=1
            result.message=('Time limit; explicit zero-launch fallback retained; global optimality unproven' if incumbent[:count_size].sum()==0 and incumbent[ridcol[goal_rid]]==0 else 'Time limit; retained feasible seed incumbent, global optimality unproven')
            dual=getattr(result,'mip_dual_bound',None)
            result.mip_gap=((-dual+result.fun)/abs(result.fun) if result.fun else (0. if dual==0 else None)) if dual is not None and np.isfinite(dual) else None

        allocation=np.zeros(n)
        for k in range(len(FUELS)):allocation[block(k)]=args.fuel_step
        earlier=np.zeros(n);mission_count=np.zeros(n)
        for slot in range(slots):
            for p,(a,b,boost) in enumerate(phases):
                for j in range(ns):
                    col=count(slot,p,j);earlier[col]=a;mission_count[col]=1
        completion=np.zeros(n);completion[makespan]=1
        args.polish_deadline=time.perf_counter()+getattr(args,'polish_seconds',10.)
        x,secondary_stages=polish_model(args,result.x,A.tocsr(),np.array(lbs),np.array(ubs),low,up,integrality,ridcol[goal_rid],
                 [('fuel allocation',allocation),('mission completion time',completion),
                  ('earlier launch phases',earlier),('mission count',mission_count)],'exact aggregate model')
        result.secondary_stages=secondary_stages
        if np.max(np.abs(x[:count_size+last_size]-np.rint(x[:count_size+last_size])))>1e-4:
            raise RuntimeError('Nonintegral solution returned')
        x[:count_size+last_size]=np.rint(x[:count_size+last_size]);x[recipes_offset:fuel_blocks_offset+len(FUELS)]=np.rint(x[recipes_offset:fuel_blocks_offset+len(FUELS)])
        detail=[];schedule=[]
        for slot in range(slots):
            actual_time=0.
            for p,(a,b,boost) in enumerate(phases):
                counts=[int(x[count(slot,p,j)]) for j in range(ns)]
                end_j=next((j for j in range(ns) if x[last(slot,p,j)]>0.5),None)
                actual_time=max(actual_time,a,float(x[start(slot,p)]) if any(counts) else a)
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
    craft_counts={rid:int(round(x[ridcol[rid]])) for rid,_ in groups}
    schedule,removed_missions,removed_crafts=remove_surplus_missions(schedule,craft_counts,groups,outputs,inventory,rate,args.event_multiplier,target)
    if removed_missions or removed_crafts:
        print(f'[Cleanup] Removed {removed_missions} surplus missions and {removed_crafts} surplus intermediate crafts; target count unchanged',flush=True)
    schedule,timing_stages=compact_fixed_schedule(args,schedule,phases)
    result.secondary_stages=getattr(result,'secondary_stages',[])+timing_stages
    x[:count_size]=0
    for slot,p,ship,boost,t,end in schedule:x[count(slot-1,p-1,available.index(ship))]+=1
    for rid,value in craft_counts.items():x[ridcol[rid]]=value
    for k in range(len(FUELS)):
        used=sum(fuel[available.index(row[2]),k] for row in schedule)
        x[block(k)]=int(np.ceil(used/args.fuel_step-1e-9))
    detail=[]
    for slot in range(slots):
        for p,(_,_,boost) in enumerate(phases):
            for j,ship in enumerate(available):
                num=int(x[count(slot,p,j)])
                if num:detail.append({'slot':slot+1,'phase':p+1,'ship':ship,'event_bonus':boost,'launches':num,
                    'total_hours':num*hours[j],'total_fuel_T':num*fuel_sum[j],**{f+'_T':num*fuel[j,k] for k,f in enumerate(FUELS)}})
    schedule_df=pd.DataFrame(schedule,columns=['slot','phase','ship','event_bonus','start_hour','end_hour'])
    for row in schedule_df.itertuples():
        a,b,boost=phases[row.phase-1]
        if not a-1e-5<=row.start_hour<b+1e-5 or row.end_hour>H+1e-5:
            raise RuntimeError(f'Schedule validation failed: {row}')
    for _,lane in schedule_df.groupby('slot'):
        lane=lane.sort_values('start_hour')
        if (lane.start_hour.to_numpy()[1:] < lane.end_hour.to_numpy()[:-1]-1e-7).any():
            raise RuntimeError('Schedule validation failed: overlapping missions')
    validate_schedule(schedule_df.to_dict('records'),launch_limit,H,dict(zip(available,hours)),slots,event_phases,sleeps)
    craft=pd.DataFrame([{'material_id':outputs[rid],'crafts':int(x[ridcol[rid]])} for rid,_ in groups if x[ridcol[rid]]>0.5], columns=['material_id','crafts'])
    balance=[]
    for mat in mats:
        source=sum(int(x[count(slot,p,j)])*rate.get((ship,mat),0)*(args.event_multiplier if boost else 1)
                   for slot in range(slots) for p,(_,_,boost) in enumerate(phases) for j,ship in enumerate(available))
        made=sum(int(x[ridcol[rid]]) for rid,g in groups if outputs[rid]==mat)
        used=sum(int(x[ridcol[rid]])*float(r.quantity) for rid,g in groups for r in g.itertuples() if r.ingredient==mat)
        balance.append({'material_id':mat,'expected_drops':source,'crafted':made,'consumed':used,'expected_remaining':inventory.get(mat,0)+source+made-used,'starting_inventory':inventory.get(mat,0)})
    plan=pd.DataFrame(detail, columns=['slot','phase','ship','event_bonus','launches','total_hours','total_fuel_T']+[f+'_T' for f in FUELS]);balance_df=pd.DataFrame(balance)
    result.upper_bound_crafts=getattr(result,'upper_bound_crafts',None)
    if result.upper_bound_crafts is None:
        dual=getattr(result,'mip_dual_bound',None)
        if result.status==0:result.upper_bound_crafts=int(x[ridcol[goal_rid]])
        elif dual is not None and np.isfinite(dual):result.upper_bound_crafts=int(np.floor(-dual+1e-6))
    print('MILP status:',result.message)
    print(f'Craft upper bound: {result.upper_bound_crafts}',flush=True)
    if result.status!=0:print('WARNING: Solution not certified globally optimal within time limit')
    print(f'Final best feasible crafts: {int(x[ridcol[goal_rid]])}; global gap: {getattr(result,"mip_gap",None)}',flush=True)
    print(f'Expected {target} crafts: {int(x[ridcol[goal_rid]])}')
    print(f'Already owned {target}: {inventory.get(target,0)}')
    print(f'Total achievable {target}: {inventory.get(target,0)+int(x[ridcol[goal_rid]])}')
    print(f'Fuel used: {plan.total_fuel_T.sum() if len(plan) else 0:.3f} / {args.fuel:g} T')
    fuel_allocation = pd.DataFrame([{'fuel':kind, 'used_T':sum(int(x[count(slot,p,j)])*fuel[j,k]
        for slot in range(slots) for p in range(np_) for j in range(ns)),
        'allocated_T':int(x[block(k)])*args.fuel_step} for k,kind in enumerate(FUELS)])
    fuel_allocation['unused_T']=fuel_allocation.allocated_T-fuel_allocation.used_T
    if (fuel_allocation.unused_T < -1e-5).any():raise RuntimeError('Fuel allocation inconsistent')
    checked_material,checked_fuel=validate_resources(schedule,craft_counts,groups,outputs,inventory,rate,args.event_multiplier,
        available,fuel,fuel_allocation.allocated_T.to_numpy(),args.fuel_step,args.fuel)
    if any(abs(row.expected_remaining-checked_material[row.material_id])>1e-6 for row in balance_df.itertuples()):
        raise ValueError('Exported balances disagree with independent mission/resource validation')
    print('Fuel allocation (in blocks of',f'{args.fuel_step:g}T):')
    print(fuel_allocation.to_string(index=False, float_format=lambda v:f'{v:.3f}'))
    print(f'Total allocated: {fuel_allocation.allocated_T.sum():.3f} / {args.fuel:g} T')
    print(f'Simultaneous ships: {args.parallel}; days: {args.days}; hypothetical events: {args.events}')
    for a,b,boost in event_phases:
        if boost:print(f'  Event: days {a/24:g} to {b/24:g}')
    if sleeps:
        print(f'Launch blackouts: {len(sleeps)} window(s)')
    completion=float(schedule_df.end_hour.max()) if len(schedule_df) else 0.
    guarantees=objective_guarantees(result,int(x[ridcol[goal_rid]]),float(fuel_allocation.allocated_T.sum()),completion)
    print(f'[Summary] Completion day {completion/24:.4f}; allocated fuel proven: {guarantees["allocated_fuel"]["proven"]}; completion proven: {guarantees["completion"]["proven"]}',flush=True)
    schedule_df['target']=schedule_df.ship.map(lambda key:mission.loc[key,'drop_target'])
    schedule_df['ship']=schedule_df.ship.map(lambda key:mission.loc[key,'base_ship'])
    plan['target']=plan.ship.map(lambda key:mission.loc[key,'drop_target'])
    plan['ship']=plan.ship.map(lambda key:mission.loc[key,'base_ship'])
    if args.output_dir:
        out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
        (out/'plan_metadata.json').write_text(json.dumps({'target':target,'missing_drop_materials':missing_rates,'unknown_drop_materials':unknown_rates,'max_launches_per_hour':launch_limit,'launch_rate_scope':'per-slot','parallel':slots,'horizon_hours':H,'zero_fuel_ships':zero_fuel_ships,'drop_profile_source':profile_info,'targeting_profile_names':profile_info['target_names'],'optimization':{'status':int(result.status),'message':result.message,'gap':finite_or_none(getattr(result,'mip_gap',None)),'solver_runs':args.solver_runs,'upper_bound_crafts':getattr(result,'upper_bound_crafts',None),'secondary_stages':getattr(result,'secondary_stages',[]),'guarantees':guarantees,'removed_surplus_missions':removed_missions}},indent=2)+'\n',encoding='utf-8')
        plan.to_csv(out/'launch_plan.csv',index=False)
        fuel_allocation.to_csv(out/'fuel_allocation.csv',index=False)
        schedule_df.to_csv(out/'schedule.csv',index=False)
        craft.to_csv(out/'craft_plan.csv',index=False)
        balance_df.to_csv(out/'material_balance.csv',index=False)
        pd.DataFrame([{'phase':i+1,'start_hour':a,'end_hour':b,'event_bonus':boost} for i,(a,b,boost) in enumerate(event_phases)]).to_csv(out/'event_windows.csv',index=False)
        pd.DataFrame([{'start_hour':a,'end_hour':b} for a,b in sleeps],columns=['start_hour','end_hour']).to_csv(out/'sleep_windows.csv',index=False)
        restrictions=[]
        for kind,daily,absolute in [('sleep',args.sleep,[]),('no-launch',[],args.no_launch)]:
            for a,b in sleep_windows(args.days,daily,absolute):restrictions.append({'start_hour':a,'end_hour':b,'kind':kind})
        pd.DataFrame(restrictions,columns=['start_hour','end_hour','kind']).to_csv(out/'launch_restrictions.csv',index=False)
        print('Output:',out)
        try:
            from build_plan_dashboard import build
            build(out, out / 'plan.html')
        except Exception as exc:
            print('Dashboard not generated:', exc)
    if 'value_note' in drops and drops.value_note.notna().any():print('CAUTION: unknown drop estimates treated as zero')

def main():
    p=argparse.ArgumentParser(description='Optimize Reggference expected crafting across multiple events')
    p.add_argument('--polish-seconds',type=float,default=10,help='Additional budget for lexicographic schedule improvement; 0 disables')
    p.add_argument('--verbose-solver',action='store_true',help='Show HiGHS progress output')
    p.add_argument('--max-launches-per-hour',type=int,default=0,help='Maximum launches per ship slot per rolling hour; 0 is unlimited')
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
    if a.days<=0 or a.fuel<0 or a.fuel_step<=0 or a.parallel<1 or a.events<0 or a.event_hours<=0 or a.event_multiplier<1 or a.max_launches_per_hour<0 or not np.isfinite(a.solver_seconds) or a.solver_seconds<=0 or not np.isfinite(a.polish_seconds) or a.polish_seconds<0:p.error('Invalid arguments')
    try:
        solve(a)
    except ValueError as exc:
        p.error(str(exc))
if __name__=='__main__':main()
