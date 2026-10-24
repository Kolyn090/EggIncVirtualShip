import contextlib
import io
import json
import unittest
from argparse import Namespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.optimize import Bounds,LinearConstraint

import test_inventory
import solver_backend
from optimize_reggference import compact_fixed_schedule,remove_surplus_missions


class LexicographicTests(unittest.TestCase):
    setUp=test_inventory.InventoryTests.setUp
    run_plan=test_inventory.InventoryTests.run_plan

    def test_ordinary_mission_moves_out_of_late_calendar_phase(self):
        args=Namespace(days=30/24,parallel=3,max_launches_per_hour=1,polish_seconds=1)
        phases=[(8,10,False),(10,12,True),(12,30,False)]
        plan=[(1,3,'test',False,29.,30.),(2,3,'test',False,29.,30.)]
        with contextlib.redirect_stdout(io.StringIO()):new,stages=compact_fixed_schedule(args,plan,phases)
        self.assertEqual([row[4] for row in new],[8.,8.])
        self.assertEqual([row[1] for row in new],[1,1])
        self.assertTrue(stages[0]['proven_in_scope'])

    def test_craft_maximum_is_never_traded_for_cheaper_crafts(self):
        mission=pd.DataFrame([dict(ship='expensive',duration='1h',**{f:5 for f in test_inventory.FUELS}),
                              dict(ship='cheap',duration='1h',**{f:1 for f in test_inventory.FUELS})])
        mission.to_csv(self.base/'mission.csv',index=False)
        pd.DataFrame([dict(ship='expensive',material_id='raw',expectation_per_launch=8),
                      dict(ship='cheap',material_id='raw',expectation_per_launch=1)]).to_csv(self.base/'ship_material_expectations.csv',index=False)
        result=self.run_plan(fuel=20,max_launches_per_hour=2,polish_seconds=3)
        self.assertEqual(result['craft_plan'].set_index('material_id').loc['metronome-4','crafts'],2)
        self.assertEqual(result['fuel_allocation'].allocated_T.sum(),20)
        self.assertEqual(set(result['schedule'].ship),{'expensive'})
        metadata=json.loads((result['out']/'plan_metadata.json').read_text())
        proof=metadata['optimization']['guarantees']
        self.assertTrue(proof['crafts']['proven'])
        self.assertTrue(proof['allocated_fuel']['proven'])
        self.assertEqual(proof['allocated_fuel']['value'],20)
        self.assertEqual(proof['crafts']['value'],2)

    def test_explicit_free_fuel_is_valid_missing_fuel_is_not_zero(self):
        mission=pd.read_csv(self.base/'mission.csv')
        for f in test_inventory.FUELS:mission[f]=0
        mission.to_csv(self.base/'mission.csv',index=False)
        result=self.run_plan(days=1/24,fuel=0,parallel=1,polish_seconds=2)
        self.assertEqual(result['fuel_allocation'].used_T.sum(),0)
        for bad in [np.nan,-1.,float('inf')]:
            invalid=mission.astype({'curiousity':float});invalid.loc[0,'curiousity']=bad
            invalid.to_csv(self.base/'mission.csv',index=False)
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'explicit finite nonnegative'):
                self.run_plan()

    def test_surplus_missions_and_intermediate_crafts_removed_without_target_loss(self):
        groups=list(pd.read_csv(self.base/'reggference.csv').groupby('recipe_id'))
        crafts={1:2,2:1}
        plan=[(1,1,'test',False,0,1),(1,2,'irrelevant',False,100,101)]
        kept,count,extra=remove_surplus_missions(plan,crafts,groups,{1:'intermediate',2:'metronome-4'},
                                               {},{('test','raw'):4,('irrelevant','raw'):0},2,'metronome-4')
        self.assertEqual(count,1)
        self.assertEqual(kept,[plan[0]])
        self.assertEqual(crafts[2],1)
        self.assertEqual(extra,0)

    def test_dashboard_summary_agrees_with_optimized_csvs_and_stage_proofs(self):
        result=self.run_plan(max_launches_per_hour=2,polish_seconds=3)
        html=(result['out']/'plan.html').read_text()
        payload=html.split('const data=',1)[1].split(';\ndocument.getElementById',1)[0]
        data=json.loads(payload)
        self.assertAlmostEqual(data['summary']['completion_hour'],result['schedule'].end_hour.max())
        self.assertAlmostEqual(data['summary']['allocated_fuel_T'],result['fuel_allocation'].allocated_T.sum())
        self.assertAlmostEqual(data['summary']['consumed_fuel_T'],result['fuel_allocation'].used_T.sum())
        self.assertEqual(data['summary']['launches'],len(result['schedule']))
        proof=data['metadata']['optimization']['guarantees']
        self.assertTrue(proof['crafts']['proven'])
        self.assertTrue(proof['allocated_fuel']['proven'])
        self.assertTrue(proof['completion']['proven'])
        self.assertIn('Minimum fuel unproven',html)
        self.assertIn('Actual completion: day',html)

    @unittest.skipIf(solver_backend.highspy is None,'Native HiGHS not installed')
    def test_native_warm_start_and_scipy_fallback_agree(self):
        args=dict(integrality=np.ones(2),bounds=Bounds([0,0],[5,5]),constraints=LinearConstraint([[1,1]],0,3),options={'time_limit':2,'disp':False})
        native=solver_backend.milp(np.array([-1.,0.]),incumbent=np.zeros(2),**args)
        with patch('solver_backend.highspy',None):fallback=solver_backend.milp(np.array([-1.,0.]),incumbent=np.zeros(2),**args)
        self.assertEqual(native.status,0)
        self.assertEqual(fallback.status,0)
        self.assertEqual(native.fun,fallback.fun)

if __name__=='__main__':unittest.main()
