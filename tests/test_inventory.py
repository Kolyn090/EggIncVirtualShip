import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import pandas as pd

from optimize_reggference import FUELS, load_inventory, solve
from build_plan_dashboard import build

ROOT = Path(__file__).resolve().parents[1]


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        pd.DataFrame([dict(ship='test', duration='1h', **{f: 1 for f in FUELS})]).to_csv(self.base/'mission.csv', index=False)
        pd.DataFrame([dict(ship='test', material_id='raw', expectation_per_launch=1)]).to_csv(self.base/'ship_material_expectations.csv', index=False)
        pd.DataFrame([(1,'intermediate','raw',2),(2,'metronome-4','intermediate',2)], columns=['recipe_id','result','ingredient','quantity']).to_csv(self.base/'reggference.csv', index=False)

    def run_plan(self, inventory=None, **options):
        out=self.base/f'output-{len(list(self.base.glob("output-*")))}'
        path=None
        if inventory is not None:
            path=self.base/'inventory.csv'
            path.write_text('material_id,quantity\n'+''.join(f'{k},{v}\n' for k,v in inventory.items()))
        args=dict(data_dir=str(self.base), expectations='ship_material_expectations.csv', ships=None,
                  inventory=path, days=1, events=0, event_hours=2, sleep=[], no_launch=[], parallel=3,
                  event_multiplier=2, fuel=20, fuel_step=5, solver_seconds=10, output_dir=str(out))
        args.update(options)
        with contextlib.redirect_stdout(io.StringIO()) as log:
            solve(Namespace(**args))
        self.assertIn('Optimal',log.getvalue())
        self.assertTrue((out/'plan.html').is_file())
        frames={n:pd.read_csv(out/f'{n}.csv') for n in ['launch_plan','craft_plan','material_balance','schedule','fuel_allocation','event_windows','sleep_windows']}
        b=frames['material_balance']
        self.assertTrue((b.expected_remaining>=-1e-5).all())
        self.assertTrue(((b.starting_inventory+b.expected_drops+b.crafted-b.consumed-b.expected_remaining).abs()<1e-5).all())
        frames['out']=out
        frames['log']=log.getvalue()
        return frames

    def test_zero_inventory_matches_baseline(self):
        a=self.run_plan()
        b=self.run_plan({'raw':0,'intermediate':0,'metronome-4':0})
        for name in ['launch_plan','craft_plan','material_balance','schedule','fuel_allocation']:
            pd.testing.assert_frame_equal(a[name],b[name])
        self.assertEqual(a['craft_plan'].set_index('material_id').loc['metronome-4','crafts'],1)

    def test_raw_inventory_can_replace_launches(self):
        baseline=self.run_plan()
        owned=self.run_plan({'raw':4},fuel=0)
        self.assertGreater(baseline['launch_plan'].launches.sum(),0)
        self.assertEqual(owned['launch_plan'].launches.sum(),0)
        self.assertEqual(owned['craft_plan'].set_index('material_id').loc['metronome-4','crafts'],1)

    def test_intermediate_inventory_is_not_recrafted(self):
        result=self.run_plan({'intermediate':2},fuel=0)
        crafts=result['craft_plan'].set_index('material_id').crafts.to_dict()
        self.assertEqual(crafts,{'metronome-4':1})
        self.assertEqual(result['material_balance'].set_index('material_id').loc['raw','consumed'],0)

    def test_owned_targets_are_counted_once(self):
        result=self.run_plan({'metronome-4':7,'intermediate':2},fuel=0)
        target=result['material_balance'].set_index('material_id').loc['metronome-4']
        self.assertEqual(target.crafted,1)
        self.assertEqual(target.expected_remaining,8)
        self.assertIn('Total achievable metronome-4: 8',result['log'])
        only=self.run_plan({'metronome-4':7},fuel=0)
        self.assertTrue(only['craft_plan'].empty)
        self.assertIn('Total achievable metronome-4: 7',only['log'])

    def test_invalid_inventory(self):
        cases=[('raw,-1','nonnegative integer'),('raw,1.5','nonnegative integer'),('raw,nan','nonnegative integer'),('raw,inf','nonnegative integer'),('raw,','nonnegative integer'),('raw,9007199254740992','maximum'),('unknown,2','unknown material'),('raw,1\nraw,2','duplicate'),('raw,1,extra','two fields'),('raw','two fields'),('"raw,1','Cannot read')]
        for body,error in cases:
            with self.subTest(body=body):
                path=self.base/'bad.csv'
                path.write_text('material_id,quantity\n'+body+'\n')
                with self.assertRaisesRegex(ValueError,error):
                    load_inventory(path,{'raw'})
        for content in ['', 'material_id,quantity,quantity\n', 'name,quantity\nraw,1\n']:
            path.write_text(content)
            with self.assertRaisesRegex(ValueError,'columns'):
                load_inventory(path,{'raw'})
        with self.assertRaisesRegex(ValueError,'Cannot read'):
            load_inventory(self.base/'missing.csv',{'raw'})
        command=subprocess.run([sys.executable,str(ROOT/'optimize_reggference.py'),'--inventory',str(path)],capture_output=True,text=True)
        self.assertEqual(command.returncode,2)
        self.assertIn('Inventory CSV',command.stderr)
        self.assertNotIn('Traceback',command.stderr)

    def test_csv_bom_reordered_columns_and_unlisted_materials(self):
        path=self.base/'inventory.csv'
        path.write_text('\ufeffquantity,material_id\n2,intermediate\n')
        self.assertEqual(load_inventory(path,{'raw','intermediate'}),{'intermediate':2})

    def test_schedule_fuel_sleep_events_and_multiplier(self):
        result=self.run_plan({'raw':1},days=2,events=2,event_multiplier=3,
                             sleep=['23:00-08:00'],no_launch=['0.5-0.6'],fuel=40)
        schedule=result['schedule']
        self.assertFalse(schedule.empty)
        self.assertTrue(schedule.slot.between(1,3).all())
        for _,g in schedule.groupby('slot'):
            g=g.sort_values('start_hour')
            self.assertTrue((g.start_hour.to_numpy()[1:]>=g.end_hour.to_numpy()[:-1]-1e-5).all())
        self.assertTrue((schedule.end_hour<=48+1e-5).all())
        for window in result['sleep_windows'].itertuples():
            self.assertFalse(((schedule.start_hour>=window.start_hour-1e-6)&(schedule.start_hour<window.end_hour-1e-6)).any())
        for row in schedule.itertuples():
            windows=result['event_windows']
            phase=windows[(windows.start_hour<=row.start_hour+1e-6)&(windows.end_hour>row.start_hour)].iloc[0]
            self.assertGreaterEqual(row.start_hour,phase.start_hour-1e-5)
            self.assertLess(row.start_hour,phase.end_hour)
            self.assertEqual(row.event_bonus,phase.event_bonus)
        allocation=result['fuel_allocation']
        self.assertLessEqual(allocation.allocated_T.sum(),40)
        self.assertTrue((allocation.allocated_T%5==0).all())
        self.assertTrue((allocation.used_T<=allocation.allocated_T+1e-5).all())
        self.assertAlmostEqual(allocation.used_T.sum(),len(schedule)*4)
        raw=result['material_balance'].set_index('material_id').loc['raw']
        self.assertAlmostEqual(raw.expected_drops,sum(3 if r.event_bonus else 1 for r in schedule.itertuples()))

    def test_dashboard_and_legacy_csv(self):
        for inventory in [None,{'metronome-4':3}]:
            result=self.run_plan(inventory)
            html=(result['out']/'plan.html').read_text()
            self.assertIn('Starting inventory</th>',html)
            self.assertIn('newly crafted +',html)
            self.assertIn('already owned',html)
            self.assertNotIn('/*__DATA__*/',html)
            self.assertIn('.tablewrap{overflow:auto;',html)
            self.assertIn('position:sticky;top:0',html)
            self.assertIn('scrollToProgress()',html)
            self.assertIn('reggference-done-v2-',html)
            result['material_balance'].drop(columns='starting_inventory').to_csv(result['out']/'material_balance.csv',index=False)
            build(result['out'],result['out']/'legacy.html')
            self.assertTrue((result['out']/'legacy.html').is_file())


if __name__=='__main__':
    unittest.main()
