import contextlib
import io
import json
from argparse import Namespace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from fuel_inventory import (INVENTORY_FUELS, FuelInventory, parse_fuel_quantity,
                            parse_initial_fuel, readable_fuel)
from optimize_reggference import solve
from schedule_validation import validate_schedule

ROOT = Path(__file__).resolve().parents[1]


class FuelQuantityTests(unittest.TestCase):
    def test_exact_quantities_and_readable_output(self):
        for text, value in [('500B','500000000000'), ('1T','1000000000000'), ('1.5t','1500000000000'),
                            ('250.5b','250500000000'), ('0','0'), ('1000000000000','1000000000000'), ('1e12','1000000000000'),
                            (' 0.000000000001T ', '1'), ('0.0000000000001T', '0.1')]:
            self.assertEqual(parse_fuel_quantity(text), Decimal(value))
        self.assertEqual(readable_fuel(Fraction(1500000000000)), '1.5T')
        self.assertEqual(readable_fuel(Fraction(250500000000)), '250.5B')
        self.assertEqual(readable_fuel(Fraction(10000000)), '0.01B')
        self.assertEqual(readable_fuel(0), '0')

    def test_invalid_quantities_types_duplicates_and_aliases(self):
        for text in ['-1', '-2T', 'NaN', 'inf', 'Infinity', '', '1Q', '1TT', '1.2.3B', '1e', 'T', '1,000B']:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Invalid fuel quantity'):
                parse_fuel_quantity(text)
        with self.assertRaisesRegex(ValueError, 'range'): parse_fuel_quantity('1'+'0'*28)
        with self.assertRaisesRegex(ValueError, 'range'): parse_fuel_quantity('1e1000000000')
        with self.assertRaisesRegex(ValueError, 'Unknown fuel type'): parse_initial_fuel(['tachyon=1T'])
        with self.assertRaisesRegex(ValueError, 'Duplicate'): parse_initial_fuel(['curiosity=1T', 'curiousity=2T'])
        stock=parse_initial_fuel(['Curiosity=1T', 'resilience=500B'])
        self.assertEqual(stock['curiousity'], 10**12)
        self.assertEqual(stock['resilence'], 500*10**9)
        self.assertNotIn('humility', stock)


class FixedFuelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name); self.number=0
        self.write_missions([dict(ship='test', duration='1h', curiousity='0.1', kindness='0.2', humility='0.00005')])
        pd.DataFrame([dict(ship='test', material_id='raw', expectation_per_launch=1)]).to_csv(self.base/'ship_material_expectations.csv',index=False)
        (self.base/'reggference.csv').write_text('recipe_id,result,ingredient,quantity\n1,metronome-4,raw,1\n')

    def write_missions(self, rows):
        pd.DataFrame([{**dict.fromkeys(INVENTORY_FUELS, '0'), **row} for row in rows]).to_csv(self.base/'mission.csv',index=False)

    def run_plan(self, stock=None, **options):
        self.number+=1; out=self.base/f'output-{self.number}'
        params=dict(data_dir=str(self.base),expectations='ship_material_expectations.csv',ships=None,inventory=None,
                    days=6/24,events=0,event_hours=1,sleep=[],no_launch=[],parallel=3,event_multiplier=2,
                    fuel=0,fuel_step=5,solver_seconds=6,polish_seconds=1,output_dir=str(out),mode='balanced',
                    fuel_mode='existing_inventory',initial_fuel=stock or [],max_launches_per_hour=0,
                    max_total_launches=0,max_launches_per_day=0)
        params.update(options)
        with contextlib.redirect_stdout(io.StringIO()) as log: solve(Namespace(**params))
        meta=json.loads((out/'plan_metadata.json').read_text())
        schedule=pd.read_csv(out/'schedule.csv'); allocation=pd.read_csv(out/'fuel_allocation.csv',dtype=str)
        if params['fuel_mode']=='existing_inventory':
            costs=pd.read_csv(self.base/'mission.csv',dtype=str).set_index('ship')
            for row in meta['fuel_inventory']:
                used=sum((Fraction(costs.loc[s,row['fuel']])*10**12 for s in schedule.ship),Fraction(0))
                self.assertEqual(used,Fraction(row['consumed_eggs']))
                exported=allocation.set_index('fuel').loc[row['fuel']]
                self.assertEqual(Fraction(exported.used_T)*10**12,used)
                if row['fuel']=='humility':
                    self.assertTrue(row['unlimited'])
                    self.assertIsNone(row['starting_eggs']);self.assertIsNone(row['remaining_eggs'])
                    self.assertEqual(row['starting'],'Unlimited');self.assertEqual(row['remaining'],'Unlimited')
                    self.assertIsNone(row['percentage_consumed'])
                    self.assertTrue(pd.isna(exported.allocated_T));self.assertTrue(pd.isna(exported.unused_T))
                    continue
                self.assertEqual(Fraction(row['starting_eggs'])-used,Fraction(row['remaining_eggs']))
                self.assertGreaterEqual(Fraction(row['remaining_eggs']),0)
                self.assertEqual(Fraction(exported.allocated_T)*10**12,Fraction(row['starting_eggs']))
                self.assertEqual(Fraction(exported.unused_T)*10**12,Fraction(row['remaining_eggs']))
            self.assertEqual(meta['fuel_validation_tolerance_eggs'],0)
            for row in pd.read_csv(out/'launch_plan.csv',dtype=str).to_dict('records'):
                total=Fraction(0)
                for fuel in INVENTORY_FUELS:
                    actual=Fraction(costs.loc[row['ship'],fuel])*int(row['launches'])
                    self.assertEqual(Fraction(row[fuel+'_T']),actual)
                    total+=actual
                self.assertEqual(Fraction(row['total_fuel_T']),total)
        return dict(out=out,meta=meta,schedule=schedule,fuel=allocation,log=log.getvalue(),
                    crafts=pd.read_csv(out/'craft_plan.csv'))

    def test_zero_and_insufficient_inventory(self):
        for stock in [[], ['curiosity=100T'], ['curiosity=99B','kindness=1T']]:
            result=self.run_plan(stock)
            self.assertTrue(result['schedule'].empty)
            self.assertTrue(result['crafts'].empty)
            self.assertTrue(all(row['percentage_consumed'] is None for row in result['meta']['fuel_inventory'] if row['starting']=='0'))

    def test_exactly_enough_and_one_egg_short(self):
        for quantity,count in [('100B',1),('99999999999',0)]:
            result=self.run_plan([f'curiosity={quantity}','kindness=200B','humility=50000000'])
            self.assertEqual(len(result['schedule']),count)
        exact=self.run_plan(['curiosity=0.3T','kindness=600B','humility=150000000'])
        self.assertEqual(len(exact['schedule']),3)
        self.assertEqual(set(exact['fuel'].loc[exact['fuel'].fuel!='humility','remaining_eggs']),{'0'})

    def test_mixed_decimal_notation_and_unused_fuel_no_allocation_rounding(self):
        result=self.run_plan(['curiosity=1.5T','kindness=250.5b','humility=100000000'],fuel_step=999)
        self.assertEqual(len(result['schedule']),1)
        rows={row['fuel']:row for row in result['meta']['fuel_inventory']}
        self.assertEqual(rows['kindness']['remaining'],'50.5B')
        self.assertEqual(rows['curiousity']['remaining'],'1.4T')
        self.assertIn('50.5B',result['log'])
        self.assertTrue(pd.isna(result['fuel'].set_index('fuel').loc['humility','allocated_T']))

    def test_multiple_ships_compete_for_shared_stock_and_all_fuels(self):
        self.write_missions([dict(ship=s,duration='1h',curiousity='.1',kindness='.2',humility='.00005') for s in ['test','better']])
        pd.DataFrame([dict(ship='test',material_id='raw',expectation_per_launch=1),
                      dict(ship='better',material_id='raw',expectation_per_launch=2)]).to_csv(self.base/'ship_material_expectations.csv',index=False)
        result=self.run_plan(['curiosity=300B','kindness=1T','humility=150000000'])
        self.assertEqual(len(result['schedule']),3)
        self.assertEqual(set(result['schedule'].ship),{'better'})
        self.assertEqual(result['crafts'].crafts.sum(),6)

    def test_four_finite_fuel_axes_are_independently_limited(self):
        self.write_missions([dict(ship='test',duration='1h',curiousity='.1',kindness='.2',
                                  resilence='.3',integrity='.4',humility='.00005')])
        stock={'curiosity':'200B','kindness':'400B','resilience':'600B','integrity':'800B','humility':'100000000'}
        result=self.run_plan(stock)
        self.assertEqual(len(result['schedule']),2)
        for name,short in [('resilience','599999999999'),('integrity','799999999999')]:
            with self.subTest(fuel=name):
                result=self.run_plan({**stock,name:short})
                self.assertEqual(len(result['schedule']),1)

    def test_secondary_consumption_objective_never_trades_crafts(self):
        self.write_missions([dict(ship='cheap',duration='1h',curiousity='.1',humility='.00005'),
                             dict(ship='expensive',duration='1h',curiousity='.3',kindness='.2',humility='.00005')])
        pd.DataFrame([dict(ship='cheap',material_id='raw',expectation_per_launch=1),
                      dict(ship='expensive',material_id='raw',expectation_per_launch=4)]).to_csv(self.base/'ship_material_expectations.csv',index=False)
        result=self.run_plan(['curiosity=300B','kindness=200B','humility=50000000'])
        self.assertEqual(result['crafts'].crafts.sum(),4)
        self.assertEqual(result['schedule'].ship.tolist(),['expensive'])

    def test_consumption_minimization_uses_exact_integer_objective_units(self):
        self.write_missions([dict(ship='a-costly',duration='1h',curiousity='.3',humility='.00005'),
                             dict(ship='b-frugal',duration='1h',curiousity='.1',humility='.00005')])
        pd.DataFrame([dict(ship=s,material_id='raw',expectation_per_launch=1) for s in ['a-costly','b-frugal']]).to_csv(self.base/'ship_material_expectations.csv',index=False)
        result=self.run_plan(['curiosity=300B','humility=50000000'],days=1/24,parallel=1)
        self.assertEqual(result['crafts'].crafts.sum(),1)
        self.assertEqual(result['schedule'].ship.tolist(),['b-frugal'])
        stages=result['meta']['optimization']['secondary_stages']
        stage=next(row for row in stages if row['objective']=='fuel consumption')
        self.assertIn('integer_fuel_unit_eggs',stage)
        self.assertAlmostEqual(stage['value'],.1)

    def test_humility_only_missions_need_no_finite_fuel_or_humility_stock(self):
        self.write_missions([dict(ship='heavy-1',duration='45m',humility='.00005')])
        (self.base/'ship_material_expectations.csv').write_text('ship,material_id,expectation_per_launch\nheavy-1,raw,1\n')
        finite=['curiosity=0','kindness=0','resilience=0','integrity=0']
        for extra in [[],['humility=0'],['humility=1']]:
            with self.subTest(extra=extra):
                result=self.run_plan(finite+extra,max_total_launches=3)
                self.assertEqual(len(result['schedule']),3)
                self.assertEqual(result['crafts'].crafts.sum(),3)
                self.assertEqual(result['meta']['fuel_inventory_totals'],dict(starting='0',consumed='0',remaining='0'))
                self.assertIn('Unlimited',result['log'])
                humility=next(row for row in result['meta']['fuel_inventory'] if row['fuel']=='humility')
                self.assertEqual(humility['consumed_eggs'],'150000000')
        for mode in ['balanced','max-crafts']:
            result=self.run_plan([],mode=mode,max_total_launches=3,max_launches_per_hour=1,sleep=['00:00-01:00'])
            self.assertEqual(result['crafts'].crafts.sum(),3)
            self.assertTrue((result['schedule'].start_hour>=1-1e-7).all())
            validate_schedule(result['schedule'].to_dict('records'),1,horizon=6,max_slots=3,max_total_launches=3)

    def test_humility_cannot_contribute_to_capacity_or_fuel_objective(self):
        costs=pd.read_csv(self.base/'mission.csv',dtype=str).set_index('ship')
        a=FuelInventory(['curiosity=300B','kindness=600B'],costs,['test'])
        b=FuelInventory(['curiosity=300B','kindness=600B','humility=1'],costs,['test'])
        self.assertEqual(a.rows,b.rows);self.assertEqual(a.launch_bound(0),3)
        self.assertNotIn('humility',a.stock);self.assertNotIn('humility',b.stock)
        self.assertEqual(a.total_unit,Fraction(300000000000))

    def test_genuinely_zero_cost_missions_are_not_excluded(self):
        self.write_missions([dict(ship='test',duration='1h')])
        result=self.run_plan([],max_total_launches=3)
        self.assertEqual(len(result['schedule']),3)
        self.assertTrue(all(row['consumed']=='0' for row in result['meta']['fuel_inventory']))

    def test_zero_fuel_preserves_material_inventory_crafting(self):
        inventory=self.base/'owned.csv';inventory.write_text('material_id,quantity\nraw,7\nmetronome-4,2\n')
        result=self.run_plan([],inventory=inventory)
        self.assertTrue(result['schedule'].empty)
        self.assertEqual(result['crafts'].crafts.sum(),7)
        self.assertIn('Total achievable metronome-4: 9',result['log'])

    def test_time_limited_feasible_result_is_not_claimed_optimal(self):
        from solver_backend import milp
        def limited(*args,**kwargs):
            result=milp(*args,**kwargs)
            if result.x is not None:result.status=1;result.message='Test time limit; feasible incumbent'
            return result
        with patch('optimize_reggference.milp',side_effect=limited):
            result=self.run_plan(['curiosity=300B','kindness=600B','humility=150000000'])
        self.assertFalse(result['schedule'].empty)
        self.assertEqual(result['meta']['optimization']['status'],1)
        self.assertFalse(result['meta']['optimization']['guarantees']['crafts']['proven'])

    def test_fast_continuous_model_sleep_events_slots_and_rate(self):
        self.write_missions([dict(ship='test',duration='15m',curiousity='.1',kindness='.2',humility='.00005')])
        result=self.run_plan(['curiosity=300B','kindness=600B','humility=150000000'],days=4/24,
                             max_launches_per_hour=1,max_total_launches=3,max_launches_per_day=3,
                             events=1,sleep=['00:00-01:00'],no_launch=['0.08-0.09'])
        self.assertEqual(len(result['schedule']),3)
        self.assertEqual(result['crafts'].crafts.sum(),6)
        validate_schedule(result['schedule'].to_dict('records'),1,horizon=4,durations={'test':.25},max_slots=3,
                          event_windows=[(r.start_hour,r.end_hour,r.event_bonus) for r in pd.read_csv(result['out']/'event_windows.csv').itertuples()],
                          blackouts=[(r.start_hour,r.end_hour) for r in pd.read_csv(result['out']/'sleep_windows.csv').itertuples()],max_total_launches=3,max_launches_per_day=3)
        self.assertTrue(result['schedule'].event_bonus.all())
        craft_search=self.run_plan(['curiosity=300B','kindness=600B','humility=150000000'],mode='max-crafts',days=4/24,
                                   max_launches_per_hour=1,max_total_launches=3,events=1,sleep=['00:00-01:00'])
        self.assertEqual(craft_search['crafts'].crafts.sum(),6)
        validate_schedule(craft_search['schedule'].to_dict('records'),1,horizon=4,max_slots=3,max_total_launches=3)

    def test_timed_zero_inventory_and_max_crafts_search(self):
        self.write_missions([dict(ship='test',duration='15m',curiousity='.1',kindness='.2',humility='.00005')])
        zero=self.run_plan([],max_launches_per_hour=1)
        self.assertTrue(zero['schedule'].empty)
        result=self.run_plan(['curiosity=300B','kindness=600B','humility=150000000'],mode='max-crafts',max_total_launches=3)
        self.assertEqual(result['crafts'].crafts.sum(),3)

    def test_incumbent_revalidated_and_cannot_overdraw(self):
        stock=['curiosity=300B','kindness=600B','humility=150000000']
        result=self.run_plan(stock)
        reused=self.run_plan(stock,incumbent_plan=result['out'])
        self.assertEqual(reused['crafts'].crafts.sum(),3)
        with self.assertRaisesRegex(ValueError,'fuel validation failed'):
            self.run_plan(['curiosity=100B','kindness=600B','humility=150000000'],incumbent_plan=result['out'])

    def test_default_mode_remains_four_fuel_five_T_budget(self):
        a=self.run_plan(fuel_mode='default',fuel=20)
        source=pd.read_csv(self.base/'mission.csv').drop(columns='humility');source.to_csv(self.base/'mission.csv',index=False)
        b=self.run_plan(fuel_mode='default',fuel=20)
        pd.testing.assert_frame_equal(a['crafts'],b['crafts'])
        pd.testing.assert_frame_equal(a['fuel'],b['fuel'])
        self.assertEqual(len(a['fuel']),4)
        self.assertTrue(all(Decimal(v)%5==0 for v in a['fuel'].allocated_T))
        with self.assertRaisesRegex(ValueError,'explicit.*humility'):
            self.run_plan(['curiosity=1T'])
        with self.assertRaisesRegex(ValueError,'requires --fuel-mode'):
            self.run_plan(['curiosity=1T'],fuel_mode='default')

    def test_exact_validator_and_numeric_scaling_limits(self):
        costs=pd.read_csv(self.base/'mission.csv',dtype=str).set_index('ship')
        stock=FuelInventory(['curiosity=99999999999','kindness=1T','humility=1T'],costs,['test'])
        with self.assertRaisesRegex(ValueError,'exact fuel validation failed'):
            stock.used([(1,1,'test',False,0,1)])
        costs.loc['test','curiousity']='0.000000000001'
        with self.assertRaisesRegex(ValueError,'exact MILP integer range'):
            FuelInventory(['curiosity=100000T'],costs,['test'])

    def test_cli_invalid_inventory_and_dashboard_data(self):
        run=subprocess.run([sys.executable,str(ROOT/'optimize_reggference.py'),'--fuel-mode','existing_inventory',
                            '--initial-fuel','curiosity=-2T'],capture_output=True,text=True)
        self.assertEqual(run.returncode,2);self.assertIn('Invalid fuel quantity',run.stderr);self.assertNotIn('Traceback',run.stderr)
        result=self.run_plan(['curiosity=350B','kindness=1T','humility=1T'])
        html=(result['out']/'plan.html').read_text()
        data=json.loads(html.split('const data=')[1].split(';\ndocument.getElementById')[0])
        self.assertEqual(data['metadata']['fuel_mode'],'existing_inventory')
        self.assertEqual(data['metadata']['fuel_inventory'],result['meta']['fuel_inventory'])
        self.assertIn('fuelInventoryTable',html)
        self.assertIn('reggference-progress-v1',html)
        from build_plan_dashboard import build
        bad=pd.read_csv(result['out']/'fuel_allocation.csv')
        bad.loc[0,'used_T']=0
        bad.to_csv(result['out']/'fuel_allocation.csv',index=False)
        with self.assertRaisesRegex(ValueError,'Fixed fuel summary'):
            build(result['out'],result['out']/'invalid.html')


if __name__=='__main__':unittest.main()
