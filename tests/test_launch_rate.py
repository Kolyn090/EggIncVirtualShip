import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import test_inventory
from optimize_reggference import validate_launch_rate, solve_timed_launches, FUELS


class LaunchRateTests(unittest.TestCase):
    setUp=test_inventory.InventoryTests.setUp
    run_plan=test_inventory.InventoryTests.run_plan

    def test_validator_rolling_boundaries_and_infeasible_schedules(self):
        for times in [[0,0,1,1],[0.99,1.01,1.99],[8,8,9],[23,23.5,24]]:
            validate_launch_rate(times,2)
        for times in [[0,0,0],[0.99,1.01,1.98],[8,8,8.01],[23.01,23.5,24]]:
            with self.subTest(times=times),self.assertRaisesRegex(ValueError,'rolling hour'):
                validate_launch_rate(times,2)
        validate_launch_rate([0]*10,0)
        for times in [[float('nan')],[float('inf')]]:
            with self.assertRaisesRegex(ValueError,'finite'):validate_launch_rate(times,2)
        with self.assertRaises(ValueError):validate_launch_rate([], -1)

    def test_simultaneous_slots_and_horizon(self):
        recipes=pd.read_csv(self.base/'reggference.csv')
        recipes['quantity']=1
        recipes.to_csv(self.base/'reggference.csv',index=False)
        limited=self.run_plan(days=2/24,fuel=100,max_launches_per_hour=2)
        unlimited=self.run_plan(days=2/24,fuel=100,max_launches_per_hour=0)
        self.assertEqual(len(limited['schedule']),4)
        self.assertEqual(len(unlimited['schedule']),6)
        validate_launch_rate(limited['schedule'].start_hour,2)
        self.assertTrue((limited['schedule'].end_hour<=2+1e-7).all())
        meta=json.loads((limited['out']/'plan_metadata.json').read_text())
        self.assertEqual(meta['max_launches_per_hour'],2)
        self.assertIn('per rolling hour',(limited['out']/'plan.html').read_text())

    def test_sleep_waking_and_events(self):
        # Six-hour horizon: launches prohibited until hour 1; event [2,4).
        result=self.run_plan(days=6/24,fuel=100,events=1,event_hours=2,
                             sleep=['00:00-01:00'],no_launch=['0.18-0.19'],max_launches_per_hour=2)
        schedule=result['schedule']
        validate_launch_rate(schedule.start_hour,2)
        self.assertTrue((schedule.start_hour>=1-1e-7).all())
        for row in schedule.itertuples():
            self.assertEqual(row.event_bonus,2-1e-7<=row.start_hour<4-1e-7)
            self.assertFalse(4.32-1e-7<=row.start_hour<4.56-1e-7)
        for _,lane in schedule.groupby('slot'):
            lane=lane.sort_values('start_hour')
            self.assertTrue((lane.start_hour.to_numpy()[1:]>=lane.end_hour.to_numpy()[:-1]-1e-7).all())
        self.assertTrue((result['fuel_allocation'].allocated_T%5==0).all())

    def test_no_completed_mission_fits(self):
        result=self.run_plan(days=0.5/24,max_launches_per_hour=2)
        self.assertTrue(result['schedule'].empty)
        self.assertTrue(result['craft_plan'].empty)

    def test_solver_infeasibility_is_not_exported(self):
        # Zero launches is normally feasible: exercise an explicit solver failure.
        from argparse import Namespace
        from types import SimpleNamespace
        args=Namespace(days=1,max_launches_per_hour=2,parallel=3,fuel=20,fuel_step=5,event_multiplier=2,solver_seconds=1)
        recipes=pd.DataFrame([dict(result='metronome-4',ingredient='raw',quantity=1)])
        with patch('optimize_reggference.milp',return_value=SimpleNamespace(x=None,message='Infeasible')):
            with self.assertRaisesRegex(RuntimeError,'Infeasible'):
                solve_timed_launches(args,['test'],np.array([1.]),np.ones((1,4)),[(0,24,False)],
                                     ['raw','metronome-4'],[(1,recipes)],{1:'metronome-4'}, {},{('test','raw'):1},'metronome-4')

if __name__=='__main__':unittest.main()
