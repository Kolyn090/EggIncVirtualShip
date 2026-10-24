import contextlib
import io
import json
import time
import unittest
from argparse import Namespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeResult
from scipy.sparse import csr_matrix

import test_inventory
from optimize_reggference import solve,FUELS,resource_upper_bound
from max_crafts_search import feasibility_status,integer_upper_bound,search
from schedule_validation import validate_schedule


class MaxCraftsTests(unittest.TestCase):
    setUp=test_inventory.InventoryTests.setUp
    run_plan=test_inventory.InventoryTests.run_plan

    def configure_mix(self):
        pd.DataFrame([dict(ship='rich',duration='4h',**{f:1 for f in FUELS}),
                      dict(ship='fast',duration='1h',**{f:1 for f in FUELS})]).to_csv(self.base/'mission.csv',index=False)
        pd.DataFrame([dict(ship='rich',material_id='raw',expectation_per_launch=4),
                      dict(ship='fast',material_id='raw',expectation_per_launch=3)]).to_csv(self.base/'ship_material_expectations.csv',index=False)

    def test_improves_seed_with_validated_alternative_and_skips_secondary(self):
        self.configure_mix()
        result=self.run_plan(mode='max-crafts',days=4/24,parallel=1,polish_seconds=100)
        self.assertEqual(result['craft_plan'].set_index('material_id').loc['metronome-4','crafts'],3)
        self.assertIn('Starting best feasible: 1',result['log'])
        self.assertNotIn('[Secondary:',result['log'])
        meta=json.loads((result['out']/'plan_metadata.json').read_text());opt=meta['optimization']
        self.assertEqual(opt['mode'],'max-crafts');self.assertEqual(opt['upper_bound_crafts'],3)
        self.assertTrue(all(stage['objective'].startswith('fixed-plan') for stage in opt['secondary_stages']))
        self.assertTrue(opt['guarantees']['crafts']['proven'])
        self.assertEqual(opt['timing']['additional_polish_seconds'],0)
        self.assertIn('feasible',[r['status'] for r in opt['craft_search']])
        html=(result['out']/'plan.html').read_text()
        self.assertIn('Validated feasible new crafts:',html);self.assertIn('Proven upper bound:',html)
        self.assertIn('Solver budget:',html);self.assertIn('Optimization runtime:',html)
        self.assertIn('"mode": "max-crafts"',html)

    def test_feasibility_classification_and_bounds_do_not_use_incumbent_as_bound(self):
        validate=lambda x:None
        for status,values,expected in [(1,None,'unknown'),(2,None,'proven_infeasible'),(1,[14.],'feasible'),(0,[14.],'feasible')]:
            result=OptimizeResult(status=status,x=None if values is None else np.array(values))
            self.assertEqual(feasibility_status(result,14,0,validate),expected)
        def invalid(x):raise ValueError('bad schedule')
        self.assertEqual(feasibility_status(OptimizeResult(status=1,x=np.array([14.])),14,0,invalid),'unknown')
        self.assertIsNone(integer_upper_bound(OptimizeResult(status=1,fun=-30)))
        self.assertEqual(integer_upper_bound(OptimizeResult(status=1,fun=-30,mip_dual_bound=-37.9)),37)

    def mock_search(self,full_status):
        args=Namespace(solver_deadline=time.monotonic()+10,solver_seconds=10)
        resource=OptimizeResult(status=0,fun=-10,x=None,resource_choices=[(False,0)])
        def simulated(args,objective,label,**kwargs):
            return OptimizeResult(status=full_status if 'full' in label else 2,x=None,fun=None,mip_dual_bound=None)
        with contextlib.redirect_stdout(io.StringIO()):
            return search(args,np.array([-1.]),csr_matrix([[1.]]),np.array([0.]),np.array([10.]),
                          np.array([0.]),np.array([10.]),np.array([1]),0,np.array([3.]),resource,
                          [np.array([0])],[(np.array([1.]),np.array([1.]))],lambda x:None,simulated)

    def test_restricted_infeasibility_and_full_timeout_never_cut_upper_bound(self):
        result=self.mock_search(1)
        self.assertEqual(result.upper_bound_crafts,10);self.assertEqual(result.x[0],3)
        self.assertEqual(result.status,1)
        self.assertTrue(all(r['status']=='unknown' for r in result.craft_search))

    def test_higher_candidate_survives_later_timeout(self):
        args=Namespace(solver_deadline=time.monotonic()+10,solver_seconds=10)
        resource=OptimizeResult(status=0,fun=-10,x=None,resource_choices=[(False,0)])
        def simulated(args,objective,label,**kwargs):
            return OptimizeResult(status=1,x=None if 'full' in label else np.array([5.]),fun=None if 'full' in label else -5.,mip_dual_bound=None)
        with contextlib.redirect_stdout(io.StringIO()):
            result=search(args,np.array([-1.]),csr_matrix([[1.]]),np.array([0.]),np.array([10.]),
                          np.array([0.]),np.array([10.]),np.array([1]),0,np.array([3.]),resource,
                          [np.array([0])],[(np.array([1.]),np.array([1.]))],lambda x:None,simulated)
        self.assertEqual(result.x[0],5);self.assertEqual(result.upper_bound_crafts,10)
        self.assertEqual(result.status,1);self.assertEqual(result.craft_search[-1]['status'],'unknown')

    def test_max_mode_respects_daily_fuel_sleep_event_and_hour_limits(self):
        mission=pd.read_csv(self.base/'mission.csv');mission['duration']='15m'
        for fuel in FUELS:mission[fuel]=0
        mission.to_csv(self.base/'mission.csv',index=False)
        recipes=pd.read_csv(self.base/'reggference.csv');recipes.quantity=1;recipes.to_csv(self.base/'reggference.csv',index=False)
        result=self.run_plan(mode='max-crafts',days=2,max_launches_per_hour=1,max_launches_per_day=2,
                             max_total_launches=3,events=1,event_hours=8,sleep=['23:00-08:00'],no_launch=['1.5-1.6'])
        validate_schedule(result['schedule'].to_dict('records'),1,48,max_slots=3,
                          event_windows=[(r.start_hour,r.end_hour,r.event_bonus) for r in result['event_windows'].itertuples()],
                          blackouts=[(r.start_hour,r.end_hour) for r in result['sleep_windows'].itertuples()],max_total_launches=3,max_launches_per_day=2)
        self.assertTrue((result['fuel_allocation'].allocated_T%5==0).all())
        self.assertTrue((result['material_balance'].expected_remaining>=-1e-5).all())

    def test_only_full_proven_infeasibility_closes_gap(self):
        result=self.mock_search(2)
        self.assertEqual(result.upper_bound_crafts,3);self.assertEqual(result.status,0)
        self.assertEqual(result.craft_search[-1]['scope'],'full model')
        self.assertEqual(result.craft_search[-1]['status'],'proven_infeasible')

    def test_balanced_can_reuse_maximum_craft_plan_and_reject_changed_constraints(self):
        self.configure_mix()
        maximum=self.run_plan(mode='max-crafts',days=4/24,parallel=1)
        balanced=self.run_plan(mode='balanced',days=4/24,parallel=1,incumbent_plan=maximum['out'])
        self.assertEqual(balanced['craft_plan'].set_index('material_id').loc['metronome-4','crafts'],3)
        meta=json.loads((balanced['out']/'plan_metadata.json').read_text())
        self.assertEqual(meta['optimization']['mode'],'balanced')
        self.assertTrue(meta['optimization']['secondary_stages'])
        with self.assertRaisesRegex(ValueError,'Total launch cap'):
            self.run_plan(mode='balanced',days=4/24,parallel=1,incumbent_plan=maximum['out'],max_total_launches=1)

    def test_timed_model_preserves_limits_and_reuses_checkpoint_as_feasibility_witness(self):
        m=pd.read_csv(self.base/'mission.csv');m['duration']='15m';m.to_csv(self.base/'mission.csv',index=False)
        recipes=pd.read_csv(self.base/'reggference.csv');recipes.quantity=1;recipes.to_csv(self.base/'reggference.csv',index=False)
        result=self.run_plan(mode='max-crafts',days=2/24,parallel=3,fuel=100,max_launches_per_hour=1,max_total_launches=10)
        self.assertEqual(len(result['schedule']),6)
        validate_schedule(result['schedule'].to_dict('records'),1,max_total_launches=10)
        resumed=self.run_plan(mode='max-crafts',days=2/24,parallel=3,fuel=100,max_launches_per_hour=1,max_total_launches=10,incumbent_plan=result['out'])
        self.assertEqual(len(resumed['schedule']),6)
        opt=json.loads((resumed['out']/'plan_metadata.json').read_text())['optimization']
        self.assertTrue(opt['guarantees']['crafts']['proven'])
        self.assertIn('proven_infeasible',[r['status'] for r in opt['craft_search']])

    def test_integer_resource_bound_preserves_integer_crafts_and_allocation_blocks(self):
        groups=list(pd.read_csv(self.base/'reggference.csv').groupby('recipe_id'))
        args=Namespace(solver_seconds=5,days=1,parallel=3,event_multiplier=2,fuel=20,fuel_step=5)
        # Three launches give 6 raw units; fractional recipes would allow 1.5.
        args.max_total_launches=3
        bound=resource_upper_bound(args,['test'],np.array([1.]),np.ones((1,4)),[(0,24,True)],
                                   ['raw','intermediate','metronome-4'],groups,{1:'intermediate',2:'metronome-4'},
                                   {},{('test','raw'):1},'metronome-4',5,integer=True)
        self.assertEqual(bound.status,0);self.assertEqual(integer_upper_bound(bound),1)
        self.assertTrue(np.allclose(bound.x,np.rint(bound.x)))

if __name__=='__main__':unittest.main()
