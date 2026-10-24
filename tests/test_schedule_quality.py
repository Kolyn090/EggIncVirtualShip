import contextlib
import io
import json
import shutil
import subprocess
import unittest
from argparse import Namespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeResult

import test_inventory
from build_plan_dashboard import describe_gap,build
from optimize_reggference import compact_fixed_schedule,polish_model,validate_launch_rate
from schedule_validation import validate_schedule


class QualityTests(unittest.TestCase):
    setUp=test_inventory.InventoryTests.setUp
    run_plan=test_inventory.InventoryTests.run_plan

    def test_long_gap_partitions_repeated_sleep_and_explicit_windows(self):
        windows=[dict(start_hour=d*24+23,end_hour=d*24+32,kind='sleep') for d in range(17)]
        windows.append(dict(start_hour=100,end_hour=110,kind='no-launch'))
        gap=describe_gap(0,404.6,windows)
        self.assertAlmostEqual(sum(gap['totals'].values()),404.6)
        self.assertGreater(gap['totals']['idle'],200)
        self.assertGreater(gap['totals']['sleep'],100)
        self.assertAlmostEqual(gap['totals']['no-launch']+gap['totals'].get('no-launch+sleep',0),10)
        for left,right in zip(gap['segments'],gap['segments'][1:]):self.assertEqual(left['end_hour'],right['start_hour'])
        self.assertEqual(gap['segments'][0]['start_hour'],0)
        self.assertEqual(gap['segments'][-1]['end_hour'],404.6)

    def test_event_wait_is_qualified_and_only_available_portions(self):
        gap=describe_gap(1,405,[dict(start_hour=399,end_hour=402,kind='sleep')],
                         [dict(start_hour=400,end_hour=448)],True)
        self.assertEqual(gap['totals']['event-wait'],398)
        self.assertEqual(gap['totals']['sleep'],3)
        self.assertEqual(gap['totals']['idle'],3)

    def test_timing_model_removes_unnecessary_hundreds_of_hours(self):
        args=Namespace(days=30,max_launches_per_hour=2,polish_seconds=2,solver_seconds=1)
        plan=[(1,1,'test',False,0,1),(1,1,'test',False,600,601)]
        with contextlib.redirect_stdout(io.StringIO()):new,stages=compact_fixed_schedule(args,plan,[(0,720,False)])
        self.assertAlmostEqual(new[1][4],1,places=5)
        self.assertAlmostEqual(new[-1][5],2,places=5)
        self.assertTrue(stages)
        # Keeping a boosted mission really requires waiting until its event.
        boosted=[plan[0],(1,2,'test',True,600,601)]
        with contextlib.redirect_stdout(io.StringIO()):new,_=compact_fixed_schedule(args,boosted,[(0,400,False),(400,700,True),(700,720,False)])
        self.assertAlmostEqual(new[1][4],400,places=5)
        self.assertEqual(new[1][3],True)

    def test_beneficial_event_and_lexicographic_fuel_and_timing(self):
        result=self.run_plan(days=6/24,fuel=20,events=1,event_hours=2,max_launches_per_hour=2,polish_seconds=5)
        crafts=result['craft_plan'].set_index('material_id').crafts
        self.assertEqual(crafts['metronome-4'],2)
        self.assertGreater(result['schedule'].event_bonus.sum(),0)
        self.assertLessEqual(result['fuel_allocation'].allocated_T.sum(),20)
        # Launch effort precedes completion: four boosted launches replace the
        # previous mix of ordinary and boosted launches.
        self.assertAlmostEqual(result['schedule'].start_hour.min(),2,places=4)
        self.assertAlmostEqual(result['schedule'].end_hour.max(),4,places=4)
        validate_schedule(result['schedule'].to_dict('records'),2)
        stages=json.loads((result['out']/'plan_metadata.json').read_text())['optimization']['secondary_stages']
        self.assertIn('fuel allocation',[s['objective'] for s in stages])
        completion=next(s for s in stages if s['objective']=='mission completion time')
        self.assertAlmostEqual(completion['value'],result['schedule'].end_hour.max(),places=4)

    def test_equivalent_solutions_no_events_choose_early_minimum_missions(self):
        for limit in [0,2]:
            result=self.run_plan(days=1,fuel=20,events=0,max_launches_per_hour=limit,polish_seconds=5)
            self.assertEqual(result['craft_plan'].set_index('material_id').loc['metronome-4','crafts'],1)
            self.assertEqual(len(result['schedule']),4)
            self.assertAlmostEqual(result['schedule'].end_hour.max(),2,places=4)
            self.assertAlmostEqual(result['fuel_allocation'].used_T.sum(),16,places=4)

    def test_secondary_timeout_preserves_crafts_and_labels_conditional_priorities(self):
        args=Namespace(solver_seconds=1,polish_seconds=1)
        result=OptimizeResult(status=1,message='Time limit',x=None,fun=None)
        with patch('optimize_reggference.run_milp',return_value=result),contextlib.redirect_stdout(io.StringIO()):
            x,stages=polish_model(args,np.array([3.,8.]),np.eye(2),[0,0],[10,10],[0,0],[10,10],[1,1],0,
                                 [('fuel',np.array([0.,1.])),('timing',np.array([0.,1.]))],'test scope')
        self.assertEqual(x[0],3)
        self.assertEqual(x[1],8)
        self.assertEqual(len(stages),2)
        self.assertFalse(stages[0]['accepted'])

    def test_validation_allows_close_cross_slot_launches_and_rejects_wrong_events(self):
        rows=[dict(slot=s,ship='test',start_hour=2+t,end_hour=3+t,event_bonus=True) for s,t in [(1,0),(2,1e-9),(3,2e-9)]]
        validate_schedule(rows,1,event_windows=[(0,2,False),(2,4,True)])
        rows[0]['event_bonus']=False
        with self.assertRaisesRegex(ValueError,'eligibility'):validate_schedule(rows[:1],2,event_windows=[(0,2,False),(2,4,True)])

    @unittest.skipUnless(shutil.which('node'),'Node is needed for dashboard JavaScript smoke test')
    def test_dashboard_boot_gap_render_and_completion_progress(self):
        result=self.run_plan(max_launches_per_hour=2,polish_seconds=2)
        html=(result['out']/'plan.html').read_text()
        script=r"""
const vm=require('vm'), assert=require('assert'), fs=require('fs');
const payload=JSON.parse(fs.readFileSync(0,'utf8'));
const nodes={}, saved={};
const element=()=>({value:'',innerHTML:'',textContent:'',addEventListener(){},appendChild(){},scrollIntoView(){}});
const document={getElementById(id){return nodes[id]??=(element())},createElement:element,addEventListener(){},querySelectorAll(){return []}};
const context=vm.createContext({document,localStorage:{getItem(k){return saved[k]||null},setItem(k,v){saved[k]=v}},console});
vm.runInContext(payload.html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
assert(nodes.lanes.innerHTML.includes('mission-cell'));
const gap=vm.runInContext('renderGap('+JSON.stringify(payload.gap)+')',context);
assert(gap.includes('<details'));assert(gap.includes('Idle / waiting'));assert(gap.includes('Sleep'));
vm.runInContext('toggleDone(missionKey(sched[0]))',context);
assert(nodes.lanes.innerHTML.includes('Completed'));assert(Object.keys(saved).some(k=>k.startsWith('reggference-done-v2-')));
"""
        gap=describe_gap(0,404.6,[dict(start_hour=23,end_hour=32,kind='sleep')])
        run=subprocess.run(['node','-e',script],input=json.dumps({'html':html,'gap':gap}),text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_dashboard_breakdown_and_invalid_plan_rejection(self):
        result=self.run_plan(max_launches_per_hour=2,polish_seconds=2)
        html=(result['out']/'plan.html').read_text()
        self.assertIn('gap-breakdown',html)
        self.assertIn('Idle / waiting',html)
        self.assertNotIn('sleeps.some',html)
        self.assertIn('mission-cell',html)
        schedule=result['schedule'].copy()
        schedule.loc[:,'start_hour']=0
        schedule.to_csv(result['out']/'schedule.csv',index=False)
        with self.assertRaises(ValueError):build(result['out'],result['out']/'invalid.html')

if __name__=='__main__':unittest.main()
