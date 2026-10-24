"""SciPy-compatible MILP adapter with native HiGHS incumbent warm starts."""
import numpy as np
from scipy.optimize import OptimizeResult, milp as scipy_milp
from scipy.sparse import vstack,csc_matrix

try:
    import highspy
except ImportError:
    highspy=None


def backend_name():
    return 'native HiGHS '+highspy.Highs().version() if highspy else 'SciPy HiGHS (no warm starts)'


def milp(c, *, integrality, bounds, constraints, options, incumbent=None):
    if highspy is None:
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
    solver.run()
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
    return result
