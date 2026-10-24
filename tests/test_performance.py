import contextlib
import io
import unittest
from argparse import Namespace
from unittest.mock import patch

import numpy as np
from scipy.optimize import OptimizeResult, milp

import test_inventory
from optimize_reggference import run_milp, solve


class PerformanceTests(unittest.TestCase):
    setUp=test_inventory.InventoryTests.setUp

    def test_solver_options_and_time_limit_incumbent(self):
        args=Namespace(solver_seconds=7.25,verbose_solver=True)
        incumbent=OptimizeResult(x=np.array([2.]),fun=-2.,status=1,message='Time limit reached',mip_gap=.5,mip_dual_bound=-3.)
        with patch('optimize_reggference.milp',return_value=incumbent) as mocked,contextlib.redirect_stdout(io.StringIO()) as out:
            result=run_milp(args,np.array([-1.]))
        self.assertIs(result,incumbent)
        self.assertEqual(mocked.call_args.kwargs['options']['time_limit'],7.25)
        self.assertTrue(mocked.call_args.kwargs['options']['disp'])
        self.assertEqual(result.fun,-2)
        self.assertIn('gap: 0.5',out.getvalue())
        self.assertIn('Finished in',out.getvalue())
        self.assertGreaterEqual(result.solver_runtime_seconds,0)

    def test_feasible_time_limit_is_exported_not_labelled_optimal(self):
        def time_limited(*a,**kw):
            kw.pop('incumbent',None)
            result=milp(*a,**kw)
            result.status=1;result.message='Time limit reached';result.mip_gap=.5
            return result
        args=Namespace(data_dir=str(self.base),expectations='ship_material_expectations.csv',ships=None,inventory=None,
                       days=1,events=0,event_hours=2,sleep=[],no_launch=[],parallel=3,event_multiplier=2,
                       fuel=20,fuel_step=5,solver_seconds=2,output_dir=str(self.base/'limited'))
        with patch('optimize_reggference.milp',side_effect=time_limited),contextlib.redirect_stdout(io.StringIO()) as out:
            solve(args)
        self.assertTrue((self.base/'limited/schedule.csv').exists())
        self.assertIn('not certified globally optimal',out.getvalue())
        self.assertNotIn('MILP status: Optimal',out.getvalue())

    def test_failed_scheduling_is_refined_not_certified(self):
        from optimize_reggference import solve_timed_launches
        def fail_nonempty(*a,**kw):
            if kw.get('launch_cap')==0:return solve_timed_launches(*a,**kw)
            raise RuntimeError('No feasible solution returned: Time limit reached')
        import pandas as pd
        mission=pd.read_csv(self.base/'mission.csv');mission['duration']='15m';mission.to_csv(self.base/'mission.csv',index=False)
        args=Namespace(data_dir=str(self.base),expectations='ship_material_expectations.csv',ships=None,inventory=None,
                       days=1,events=0,event_hours=2,sleep=[],no_launch=[],parallel=3,event_multiplier=2,
                       fuel=20,fuel_step=5,solver_seconds=2,max_launches_per_hour=1,output_dir=str(self.base/'refined'))
        with patch('optimize_reggference.solve_timed_launches',side_effect=fail_nonempty),contextlib.redirect_stdout(io.StringIO()) as out:
            solve(args)
        self.assertIn('[Refine]',out.getvalue())
        self.assertIn('global optimality not proven',out.getvalue())
        self.assertIn('Final best feasible crafts: 0',out.getvalue())

    def test_no_incumbent_retains_explicit_safe_fallback(self):
        args=Namespace(data_dir=str(self.base),expectations='ship_material_expectations.csv',ships=None,inventory=None,
                       days=1,events=0,event_hours=2,sleep=[],no_launch=[],parallel=3,event_multiplier=2,
                       fuel=20,fuel_step=5,solver_seconds=2,output_dir=str(self.base/'fallback'))
        result=OptimizeResult(x=None,fun=None,status=1,message='Time limit reached')
        with patch('optimize_reggference.milp',return_value=result),contextlib.redirect_stdout(io.StringIO()) as out:
            solve(args)
        self.assertIn('explicit zero-launch fallback',out.getvalue())
        self.assertTrue((self.base/'fallback/plan.html').exists())

if __name__=='__main__':unittest.main()
