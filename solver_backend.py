"""Deadline-supervised MILP adapter with native HiGHS incumbent warm starts."""
import multiprocessing
import os
import pickle
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np
from scipy.optimize import OptimizeResult, milp as scipy_milp
from scipy.sparse import vstack,csc_matrix

try:
    import highspy
except ImportError:
    highspy=None


def backend_name():
    return 'native HiGHS '+highspy.Highs().version() if highspy else 'SciPy HiGHS (no warm starts)'


def _milp_in_process(c, *, integrality, bounds, constraints, options, incumbent=None, checkpoint=None, phase=None, use_native=True, deadline=None):
    setup_started=time.monotonic()
    if deadline is not None and setup_started>=deadline:
        return OptimizeResult(status=1,message='Worker allocation expired before setup',x=None,fun=None)
    if phase:phase({'phase':'native_setup' if highspy is not None and use_native else 'scipy_setup','setup_started':setup_started})
    if highspy is None or not use_native:
        if deadline is not None:options={**options,'time_limit':min(options['time_limit'],max(0.,deadline-time.monotonic()))}
        if options['time_limit']<=0:return OptimizeResult(status=1,message='Worker deadline before SciPy solve',x=None,fun=None)
        if phase:phase({'phase':'scipy_run','run_started':time.monotonic(),'native_requested_seconds':options['time_limit']})
        return scipy_milp(c,integrality=integrality,bounds=bounds,constraints=constraints,options=options)
    items=constraints if isinstance(constraints,(list,tuple)) else [constraints]
    matrix=vstack([csc_matrix(item.A) for item in items],format='csc')
    lower=np.concatenate([np.broadcast_to(item.lb,item.A.shape[0]) for item in items])
    upper=np.concatenate([np.broadcast_to(item.ub,item.A.shape[0]) for item in items])
    lp=highspy.HighsLp()
    lp.num_col_=len(c);lp.num_row_=matrix.shape[0]
    lp.col_cost_=np.asarray(c,dtype=float)
    lp.col_lower_=np.broadcast_to(bounds.lb,len(c)).astype(float)
    lp.col_upper_=np.broadcast_to(bounds.ub,len(c)).astype(float)
    lp.row_lower_=lower;lp.row_upper_=upper
    lp.a_matrix_.format_=highspy.MatrixFormat.kColwise
    lp.a_matrix_.start_=matrix.indptr.astype(np.int32)
    lp.a_matrix_.index_=matrix.indices.astype(np.int32)
    lp.a_matrix_.value_=matrix.data
    discrete=np.broadcast_to(0 if integrality is None else integrality,len(c))!=0
    lp.integrality_=[highspy.HighsVarType.kInteger if value else highspy.HighsVarType.kContinuous for value in discrete]
    solver=highspy.Highs()
    settings={'output_flag':options.get('disp',False),'time_limit':options['time_limit'],'mip_rel_gap':options.get('mip_rel_gap',0.),
              'mip_feasibility_tolerance':1e-9,'primal_feasibility_tolerance':1e-9,'dual_feasibility_tolerance':1e-9,'threads':1,'presolve':'on' if options.get('presolve',True) else 'off'}
    for key,value in settings.items():
        if solver.setOptionValue(key,value)==highspy.HighsStatus.kError:raise RuntimeError('HiGHS rejected option '+key)
    if solver.passModel(lp)==highspy.HighsStatus.kError:raise RuntimeError('HiGHS rejected model')
    if incumbent is not None:
        solution=highspy.HighsSolution();solution.col_value=np.asarray(incumbent,dtype=float)
        if solver.setSolution(solution)==highspy.HighsStatus.kError:raise RuntimeError('HiGHS rejected incumbent')
    if checkpoint:
        def save_incumbent(event):
            output=event.data_out
            values=np.array(output.mip_solution,copy=True)
            checkpoint(OptimizeResult(status=1,message='Validated checkpoint; proof incomplete',x=values,
                       fun=float(np.asarray(c)@values),mip_dual_bound=float(output.mip_dual_bound),
                       mip_gap=float(output.mip_gap)))
        solver.cbMipImprovingSolution.subscribe(save_incumbent)
    setup_seconds=time.monotonic()-setup_started
    run_started=time.monotonic()
    native_requested_seconds=min(options['time_limit'],deadline-run_started) if deadline is not None else options['time_limit']
    if native_requested_seconds<=0:return OptimizeResult(status=1,message='Worker deadline before native solve',x=None,fun=None)
    solver.setOptionValue('time_limit',native_requested_seconds)
    if phase:phase({'phase':'highs_run','run_started':run_started,'native_setup_seconds':setup_seconds,'native_requested_seconds':native_requested_seconds})
    solver.run()
    native_run_seconds=time.monotonic()-run_started
    status=solver.getModelStatus();info=solver.getInfo();solution=solver.getSolution()
    code={highspy.HighsModelStatus.kOptimal:0,highspy.HighsModelStatus.kInfeasible:2,
          highspy.HighsModelStatus.kUnbounded:3}.get(status,
          1 if status in [getattr(highspy.HighsModelStatus,name,None) for name in
                         ['kTimeLimit','kIterationLimit','kSolutionLimit','kObjectiveBound','kObjectiveTarget','kMemoryLimit','kInterrupt']] else 4)
    feasible=info.primal_solution_status==highspy.SolutionStatus.kSolutionStatusFeasible
    result=OptimizeResult(status=code,message=solver.modelStatusToString(status),
                          x=np.array(solution.col_value) if feasible else None,
                          fun=float(info.objective_function_value) if feasible else None,
                          mip_dual_bound=float(info.mip_dual_bound) if discrete.any() else (float(info.objective_function_value) if code==0 else None),
                          mip_gap=float(info.mip_gap) if discrete.any() else (0. if code==0 else None),
                          mip_node_count=int(info.mip_node_count))
    result.native_requested_seconds=native_requested_seconds
    result.native_setup_seconds=setup_seconds
    result.native_run_seconds=native_run_seconds
    result.highs_reported_seconds=solver.getRunTime()
    return result


def _atomic_pickle(path, value):
    temporary=str(path)+'.tmp'
    with open(temporary,'wb') as stream:pickle.dump(value,stream,protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(temporary,path)


def _read_pickle(path):
    try:
        with open(path,'rb') as stream:return pickle.load(stream)
    except FileNotFoundError:return None


def _worker(request_path, directory):
    directory=Path(directory)
    try:
        request=_read_pickle(request_path)
        result=_milp_in_process(**request,
            checkpoint=lambda result:_atomic_pickle(directory/'checkpoint',result),
            phase=lambda phase:_atomic_pickle(directory/'phase',phase))
        _atomic_pickle(directory/'result',{'result':result,'finished':time.monotonic()})
    except BaseException:
        _atomic_pickle(directory/'result',{'error':traceback.format_exc(),'finished':time.monotonic()})


def feasible_vector(x, *, c, integrality, bounds, constraints):
    """Validate checkpoints against the ORIGINAL full model, never a relaxation."""
    if x is None:return False
    x=np.asarray(x,dtype=float)
    if x.shape!=(len(c),) or not np.isfinite(x).all():return False
    if (x<np.asarray(bounds.lb)-1e-6).any() or (x>np.asarray(bounds.ub)+1e-6).any():return False
    integer=np.broadcast_to(0 if integrality is None else integrality,len(c))
    # This project uses continuous and ordinary integer variables only.
    if not np.isin(integer,[0,1]).all():raise ValueError('Unsupported integrality type in checkpoint validator')
    if (np.abs(x[integer==1]-np.rint(x[integer==1]))>1e-5).any():return False
    items=constraints if isinstance(constraints,(list,tuple)) else [constraints]
    for item in items:
        values=item.A@x
        if (values<np.asarray(item.lb)-1e-5).any() or (values>np.asarray(item.ub)+1e-5).any():return False
    return True


def _stop_worker(process):
    if process.is_alive():
        # Atomic checkpoints are already closed before rename. No worker owns
        # external application state, so immediate kill is safe at its deadline.
        process.kill()
        process.join(1.)
    else:process.join()


def milp(c, *, integrality, bounds, constraints, options, incumbent=None):
    """Wall-clock supervised solve. Native time_limit alone is not interruptible.

    Startup, serialization and native model transfer consume the same stage
    allocation. Termination/reaping and checkpoint validation are measured
    overhead, not a hard real-time guarantee for the Python command.
    """
    started=time.monotonic()
    settings=dict(options)
    deadline=min(started+settings['time_limit'],settings.pop('wall_deadline',float('inf')))
    use_native=highspy is not None
    settings={k:v for k,v in settings.items() if k!='wall_deadline'}
    model=dict(c=c,integrality=integrality,bounds=bounds,constraints=constraints)
    prior=None
    if feasible_vector(incumbent,**model):
        prior=OptimizeResult(status=1,message='Retained validated incumbent',x=np.asarray(incumbent).copy(),
                             fun=float(np.asarray(c)@incumbent),mip_dual_bound=None,mip_gap=None)
    result=None;terminated=False;phase={};launched=False
    with tempfile.TemporaryDirectory(prefix='egginc-solver-') as directory:
        folder=Path(directory)
        request=dict(**model,options=settings,incumbent=incumbent,use_native=use_native,deadline=deadline)
        _atomic_pickle(folder/'request',request)
        if time.monotonic()<deadline:
            # forkserver avoids inheriting native threads/HiGHS state; spawn is
            # the portable fallback. Preloading amortizes imports after stage 1.
            method='forkserver' if 'forkserver' in multiprocessing.get_all_start_methods() else 'spawn'
            if method=='forkserver':multiprocessing.set_forkserver_preload(['solver_backend'])
            process=multiprocessing.get_context(method).Process(target=_worker,args=(str(folder/'request'),directory))
            try:
                process.start();launched=True
                while time.monotonic()<deadline:
                    if (folder/'result').exists():break
                    process.join(min(.01,max(0.,deadline-time.monotonic())))
                    if not process.is_alive():break
                finished=_read_pickle(folder/'result')
                if finished is None and not process.is_alive() and process.exitcode not in [None,0]:
                    raise RuntimeError(f'Solver worker exited unexpectedly ({process.exitcode})')
                terminated=finished is None or finished['finished']>deadline
                _stop_worker(process)
                phase=_read_pickle(folder/'phase') or {}
                if finished is not None and 'error' in finished:raise RuntimeError('Solver worker failed:\n'+finished['error'])
                if finished is not None and not terminated:result=finished['result']
                else:result=_read_pickle(folder/'checkpoint')
            finally:
                if process.pid is not None:
                    _stop_worker(process)
                    if not process.is_alive():process.close()
        if result is not None and result.x is not None and not feasible_vector(result.x,**model):
            result=OptimizeResult(status=1,message='Invalid worker checkpoint rejected',x=None,fun=None)
        if prior is not None and (result is None or result.x is None or prior.fun<result.fun-1e-7):
            if result is not None:
                prior.mip_dual_bound=getattr(result,'mip_dual_bound',None)
            result=prior
        if result is None:result=OptimizeResult(status=1,message='Wall-clock budget exhausted; no validated incumbent',x=None,fun=None)
        if terminated or not launched:
            result.status=1
            result.message=('Wall-clock deadline; retained validated checkpoint' if result.x is not None else
                            'Wall-clock deadline; no validated incumbent')
            bound=getattr(result,'mip_dual_bound',None)
            result.mip_gap=(max(0.,(result.fun-bound)/abs(result.fun)) if result.fun else (0. if bound==0 else None)) if result.fun is not None and bound is not None and np.isfinite(bound) else None
        result.worker_terminated=terminated
        result.worker_started=launched
        result.worker_phase=phase.get('phase','startup_or_serialization')
        result.native_setup_seconds=getattr(result,'native_setup_seconds',phase.get('native_setup_seconds'))
        result.native_run_seconds=getattr(result,'native_run_seconds',time.monotonic()-phase['run_started'] if 'run_started' in phase else None)
        result.native_requested_seconds=getattr(result,'native_requested_seconds',phase.get('native_requested_seconds'))
        result.wall_runtime_seconds=time.monotonic()-started
        result.requested_seconds=settings['time_limit']
        result.exceeded_requested_limit=result.wall_runtime_seconds>settings['time_limit']+.02
        return result
