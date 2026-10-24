import contextlib
import io
import json
import time
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.optimize import Bounds,LinearConstraint,OptimizeResult

import solver_backend
from optimize_reggference import run_milp


def stalled_worker(request_path,directory):
    request=solver_backend._read_pickle(request_path)
    solver_backend._atomic_pickle(Path(directory)/'checkpoint',OptimizeResult(status=1,x=np.array([2.]),fun=-2.,mip_dual_bound=-3.,mip_gap=.5))
    time.sleep(30)


def invalid_worker(request_path,directory):
    solver_backend._atomic_pickle(Path(directory)/'checkpoint',OptimizeResult(status=1,x=np.array([100.]),fun=-100.))
    time.sleep(30)


class RuntimeTests(unittest.TestCase):
    def model(self):
        return dict(integrality=np.ones(1),bounds=Bounds([0],[3]),constraints=LinearConstraint([[1]],0,3))

    def test_expired_deadline_never_calls_backend(self):
        args=Namespace(solver_seconds=5,solver_deadline=time.monotonic()-1)
        with patch('optimize_reggference.milp') as solve,contextlib.redirect_stdout(io.StringIO()):
            result=run_milp(args,np.array([-1.]))
        solve.assert_not_called();self.assertEqual(result.status,1);self.assertIsNone(result.x)

    def test_remaining_time_clamped_to_shared_monotonic_deadline(self):
        args=Namespace(solver_seconds=120,solver_deadline=time.monotonic()+.2,solver_runs=[])
        with patch('optimize_reggference.milp',return_value=OptimizeResult(status=1,message='limit',x=None,fun=None)) as solve,contextlib.redirect_stdout(io.StringIO()):
            run_milp(args,np.array([-1.]),seconds=30)
        self.assertGreater(solve.call_args.kwargs['options']['time_limit'],0)
        self.assertLessEqual(solve.call_args.kwargs['options']['time_limit'],.2)
        self.assertIn('exceeded_requested_limit',args.solver_runs[0])

    def test_stalled_worker_is_killed_and_valid_checkpoint_retained(self):
        # Warm the safe fork server; startup time is also charged in production.
        solver_backend.milp(np.array([-1.]),**self.model(),options={'time_limit':2})
        started=time.monotonic()
        with patch('solver_backend._worker',stalled_worker):
            result=solver_backend.milp(np.array([-1.]),**self.model(),options={'time_limit':1.5},incumbent=np.array([1.]))
        self.assertLess(time.monotonic()-started,3.)
        self.assertTrue(result.worker_terminated);self.assertEqual(result.status,1)
        self.assertEqual(result.x[0],2);self.assertEqual(result.fun,-2)
        self.assertEqual(result.mip_dual_bound,-3)

    def test_invalid_checkpoint_rejected_and_prior_validated_incumbent_retained(self):
        with patch('solver_backend._worker',invalid_worker):
            result=solver_backend.milp(np.array([-1.]),**self.model(),options={'time_limit':1.5},incumbent=np.array([1.]))
        self.assertEqual(result.status,1);self.assertEqual(result.x[0],1)

    def test_scipy_worker_is_also_supervised(self):
        with patch('solver_backend.highspy',None),patch('solver_backend._worker',stalled_worker):
            result=solver_backend.milp(np.array([-1.]),**self.model(),options={'time_limit':1.5})
        self.assertTrue(result.worker_terminated);self.assertEqual(result.status,1)

    def test_no_new_secondary_stage_after_shared_budget_expires(self):
        from optimize_reggference import polish_model
        args=Namespace(solver_seconds=5,polish_seconds=120,overall_deadline=time.monotonic()-1)
        with patch('optimize_reggference.run_milp') as solve:
            x,stages=polish_model(args,np.array([2.]),np.eye(1),[0],[3],[0],[3],[1],0,[('launch count',np.array([1.]))],'test')
        solve.assert_not_called();self.assertEqual(stages,[]);self.assertEqual(x[0],2)

if __name__=='__main__':unittest.main()
