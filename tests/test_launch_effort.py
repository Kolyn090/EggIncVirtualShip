import json
import unittest
from argparse import Namespace
from pathlib import Path
import pandas as pd

import test_inventory
from schedule_validation import validate_schedule
from optimize_reggference import FUELS,compact_fixed_schedule


class LaunchEffortTests(unittest.TestCase):
    setUp=test_inventory.InventoryTests.setUp
    run_plan=test_inventory.InventoryTests.run_plan

    def test_total_cap_in_both_model_formulations(self):
        for duration,limit in [('1h',0),('15m',1)]:
            m=pd.read_csv(self.base/'mission.csv');m['duration']=duration
            for fuel in FUELS:m[fuel]=0
            m.to_csv(self.base/'mission.csv',index=False)
            pd.DataFrame([dict(ship='test',material_id='raw',expectation_per_launch=4)]).to_csv(self.base/'ship_material_expectations.csv',index=False)
            result=self.run_plan(days=2/24,max_total_launches=3,max_launches_per_hour=limit,polish_seconds=3)
            self.assertEqual(len(result['schedule']),3)
            self.assertEqual(result['craft_plan'].set_index('material_id').loc['metronome-4','crafts'],3)
            validate_schedule(result['schedule'].to_dict('records'),limit,max_total_launches=3)

    def test_effort_before_fuel_keeps_free_ships_and_craft_count(self):
        pd.DataFrame([dict(ship='free',duration='1h',**{f:0 for f in FUELS}),
                      dict(ship='paid',duration='1h',**{f:5 for f in FUELS})]).to_csv(self.base/'mission.csv',index=False)
        pd.DataFrame([dict(ship='free',material_id='raw',expectation_per_launch=1),
                      dict(ship='paid',material_id='raw',expectation_per_launch=4)]).to_csv(self.base/'ship_material_expectations.csv',index=False)
        result=self.run_plan(days=8/24,parallel=1,fuel=20,polish_seconds=3)
        self.assertEqual(result['craft_plan'].set_index('material_id').loc['metronome-4','crafts'],2)
        self.assertEqual(len(result['schedule']),5)
        self.assertEqual((result['schedule'].ship=='free').sum(),4)
        self.assertEqual(result['fuel_allocation'].allocated_T.sum(),20)
        metadata=json.loads((result['out']/'plan_metadata.json').read_text())
        stages=metadata['optimization']['secondary_stages']
        self.assertEqual([x['objective'] for x in stages[:3]],['launch count','fuel allocation','mission completion time'])
        self.assertTrue(metadata['optimization']['guarantees']['launch_count']['proven'])
        for stage in stages[:3]:self.assertEqual(stage['fixed_craft_count'],2)

    def test_daily_cap_across_slots_with_sleep_and_events(self):
        m=pd.read_csv(self.base/'mission.csv')
        for f in FUELS:m[f]=0
        m.to_csv(self.base/'mission.csv',index=False)
        pd.DataFrame([dict(ship='test',material_id='raw',expectation_per_launch=4)]).to_csv(self.base/'ship_material_expectations.csv',index=False)
        for duration,limit in [('1h',1),('15m',1)]:
            m['duration']=duration;m.to_csv(self.base/'mission.csv',index=False)
            result=self.run_plan(days=2,events=1,event_hours=8,sleep=['23:00-08:00'],
                                 max_launches_per_hour=limit,max_launches_per_day=2,max_total_launches=3,polish_seconds=3)
            self.assertLessEqual(len(result['schedule']),3)
            counts=(result['schedule'].start_hour//24).value_counts()
            self.assertLessEqual(counts.max(),2)
            validate_schedule(result['schedule'].to_dict('records'),limit,max_total_launches=3,max_launches_per_day=2)
            meta=json.loads((result['out']/'plan_metadata.json').read_text())
            self.assertEqual(meta['max_total_launches'],3);self.assertEqual(meta['max_launches_per_day'],2)
            html=(result['out']/'plan.html').read_text()
            self.assertIn('Minimum launch count proven',html);self.assertIn('Total launch cap:',html)

    def test_service_union_bound_and_resource_lp_are_valid_relaxations(self):
        import numpy as np
        from optimize_reggference import resource_upper_bound,service_capacity
        self.assertEqual(service_capacity([(0,1,True),(1,2,False),(2,3,True)],True,2,10),5)
        recipes=pd.read_csv(self.base/'reggference.csv');groups=list(recipes.groupby('recipe_id'))
        args=Namespace(solver_seconds=5,days=2/24,parallel=3,event_multiplier=2,fuel=20,fuel_step=5,max_total_launches=3)
        result=resource_upper_bound(args,['test'],np.array([1.]),np.ones((1,4)),[(0,2,True)],
                                    ['raw','intermediate','metronome-4'],groups,{1:'intermediate',2:'metronome-4'},
                                    {},{('test','raw'):1},'metronome-4',5)
        self.assertEqual(result.status,0);self.assertAlmostEqual(-result.fun,1.5)

    def test_validator_day_boundaries_and_global_caps(self):
        rows=[dict(slot=s,ship='test',start_hour=t,end_hour=t+.1) for s,t in [(1,23.9),(2,23.9),(3,24.)]]
        validate_schedule(rows,1,max_total_launches=3,max_launches_per_day=2)
        with self.assertRaisesRegex(ValueError,'Total'):validate_schedule(rows,max_total_launches=2)
        with self.assertRaisesRegex(ValueError,'Daily'):validate_schedule(rows,max_launches_per_day=1)

    def test_calendar_compaction_preserves_daily_assignment(self):
        args=Namespace(days=3,parallel=3,max_launches_per_hour=1,max_launches_per_day=1)
        plan=[(1,1,'test',False,10.,11.),(2,2,'test',False,35.,36.)]
        new,_=compact_fixed_schedule(args,plan,[(0,24,False),(24,48,False),(48,72,False)])
        validate_schedule([dict(slot=r[0],ship=r[2],event_bonus=r[3],start_hour=r[4],end_hour=r[5]) for r in new],1,max_launches_per_day=1)
        self.assertEqual([int(r[4]//24) for r in new],[0,1])

if __name__=='__main__':unittest.main()
