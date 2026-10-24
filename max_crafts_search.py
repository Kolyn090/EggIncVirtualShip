"""Craft-focused orchestration on the optimizer's existing, unchanged model."""
import time
import numpy as np
from scipy.optimize import Bounds,LinearConstraint,OptimizeResult
from solver_backend import feasible_vector


def integer_upper_bound(result):
    """Only dual bounds (or a proved optimum) certify an upper bound."""
    dual=getattr(result,'mip_dual_bound',None)
    if getattr(result,'status',None)==0 and getattr(result,'fun',None) is not None:dual=result.fun
    return int(np.floor(-dual+1e-6)) if dual is not None and np.isfinite(dual) else None


def feasibility_status(result, threshold, goal, validate):
    if result.x is not None and round(result.x[goal])>=threshold:
        try:validate(result.x)
        except (ValueError,RuntimeError):return 'unknown'
        return 'feasible'
    return 'proven_infeasible' if result.status==2 else 'unknown'


def reduced_model(matrix, low, up, integer, columns, lbs=None, ubs=None):
    """Eliminate FIXED ZERO columns and redundant zero rows exactly."""
    high=up.copy();high[~columns]=0
    keep=(high!=0)|(low!=0)
    reduced=matrix[:,keep].tocsr()
    reduced.eliminate_zeros()
    rows=np.diff(reduced.indptr)>0
    if lbs is not None:rows|=(np.asarray(lbs)>0)|(np.asarray(ubs)<0)
    return keep,rows,reduced[rows],high


def search(args, objective, matrix, lbs, ubs, low, up, integer, goal, incumbent,
           resource_result, option_columns, option_rates, validate, solve):
    """Adaptive threshold searches. Restrictions discover witnesses, never bounds.

    Matrix slices are cached per option set. Warm starts/checkpoints reuse the
    validated incumbent; the full unrestricted model is kept for certification.
    """
    best=incumbent.copy();validate(best)
    if resource_result.status==2:raise RuntimeError('Resource infeasibility contradicts the validated scheduling incumbent')
    upper=integer_upper_bound(resource_result)
    print(f'[Max Crafts] Starting best feasible: {int(round(best[goal]))}; proven upper bound: {upper}',flush=True)
    records=[];cache={}
    started=time.monotonic();remaining=max(0.,args.solver_deadline-started)
    candidate_deadline=started+remaining*.72
    profiles=set()
    if resource_result.x is not None:
        for i,(_,j) in enumerate(resource_result.resource_choices):
            if resource_result.x[i]>.5:profiles.add(j)
    profiles|={j for j,cols in enumerate(option_columns) if np.any(best[cols]>.5)}
    # Rank separately for each ingredient: both units/launch and units/hour
    # candidates can matter. Full search never excludes another legal option.
    choices=[]
    if profiles:choices.append(('integer-resource mix',profiles.copy()))
    for breadth in [1,2,4]:
        candidate=set(profiles)
        for values in option_rates:
            for scores in values:
                candidate.update(int(j) for j in np.argsort(-scores,kind='stable')[:breadth] if scores[j]>0)
        if not choices or candidate!=choices[-1][1]:choices.append((f'ingredient alternatives {breadth}',candidate))
    for number,(name,selected) in enumerate(choices):
        now=time.monotonic();threshold=int(round(best[goal]))+1
        if now>=candidate_deadline or upper is not None and threshold>upper:break
        key=tuple(sorted(selected))
        if key not in cache:
            columns=np.ones(len(objective),dtype=bool)
            for j,cols in enumerate(option_columns):
                if j not in selected:columns[cols]=False
            keep,rows,sub,high=reduced_model(matrix,low,up,integer,columns,lbs,ubs)
            cache[key]=(keep,rows,sub,high)
            if hasattr(args,'construction_totals'):args.construction_totals.append(time.monotonic()-now)
        keep,rows,sub,high=cache[key]
        sublow=low[keep].copy();subgoal=int(np.flatnonzero(np.flatnonzero(keep)==goal)[0]);sublow[subgoal]=threshold
        if time.monotonic()>=candidate_deadline:break
        allocated=min(45.,max(.01,(candidate_deadline-time.monotonic())/(len(choices)-number)))
        print(f'[Max Crafts] Testing >= {threshold}: {name}, {len(selected)} options (restricted witness search)',flush=True)
        result=solve(args,objective[keep],label=f'Max crafts candidate >= {threshold}',seconds=allocated,
                     integrality=integer[keep],bounds=Bounds(sublow,high[keep]),
                     constraints=LinearConstraint(sub,lbs[rows],ubs[rows]),incumbent=best[keep])
        lifted=OptimizeResult(status=result.status,x=None,fun=getattr(result,'fun',None))
        if result.x is not None:
            lifted.x=np.zeros(len(objective));lifted.x[keep]=result.x
        status=feasibility_status(lifted,threshold,goal,validate)
        if status=='proven_infeasible':status='unknown'
        records.append({'threshold':threshold,'scope':'restricted witness search','strategy':name,'status':status,
                        'best_feasible':int(round(lifted.x[goal])) if status=='feasible' else int(round(best[goal])),'solver_status':int(result.status),'runtime_seconds':getattr(result,'solver_runtime_seconds',0)})
        if status=='feasible':best=lifted.x.copy()
        print(f'[Max Crafts] {status}; best feasible {int(round(best[goal]))}; proven upper bound {upper}',flush=True)
        # A restricted-model infeasibility says NOTHING about global feasibility.
    if upper is None or round(best[goal])<upper:
        threshold=int(round(best[goal]))+1
        remaining=args.solver_deadline-time.monotonic()
        if remaining>0:
            full_low=low.copy();full_low[goal]=threshold
            print(f'[Max Crafts] Testing >= {threshold}: full model, all options retained',flush=True)
            result=solve(args,objective,label=f'Max crafts full >= {threshold}',seconds=remaining,
                         integrality=integer,bounds=Bounds(full_low,up),constraints=LinearConstraint(matrix,lbs,ubs),incumbent=best)
            status=feasibility_status(result,threshold,goal,validate)
            records.append({'threshold':threshold,'scope':'full model','status':status,'solver_status':int(result.status),
                            'runtime_seconds':getattr(result,'solver_runtime_seconds',0)})
            if status=='feasible':best=result.x.copy()
            if status=='proven_infeasible':upper=threshold-1 if upper is None else min(upper,threshold-1)
            # Dual bounds for the cutoff model cover >= threshold; lower crafts
            # are bounded by threshold-1 even if no cutoff witness was found.
            bound=integer_upper_bound(result) if result.status!=0 or status=='feasible' else None
            if bound is not None:
                bound=max(threshold-1,bound)
                upper=bound if upper is None else min(upper,bound)
    lower=int(round(best[goal]))
    if upper is not None and upper<lower:raise RuntimeError('Certified upper bound contradicts validated incumbent')
    proven=upper is not None and upper==lower
    final=OptimizeResult(x=best,fun=float(objective@best),status=0 if proven else 1,
                         message='Craft maximum proven by matching bounds' if proven else 'Feasible plan; craft maximum unproven (max-crafts search)',
                         mip_dual_bound=-upper if upper is not None else None,
                         mip_gap=(upper-lower)/abs(lower) if upper is not None and lower else (0. if upper==0 else None),
                         upper_bound_crafts=upper,craft_search=records)
    print(f'[Max Crafts] Final: best feasible {lower}; proven upper bound {upper}; optimality {"proven" if proven else "not proven"}',flush=True)
    return final
