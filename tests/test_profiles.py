import contextlib
import io
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import pandas as pd

import test_inventory
from mission_profiles import load_recipes,expand_profiles,prune_dominated_options
from build_plan_dashboard import build


class ProfileTests(unittest.TestCase):
    setUp=test_inventory.InventoryTests.setUp
    run_plan=test_inventory.InventoryTests.run_plan

    def test_generic_recipe_discovery_deduplicates_and_namespaces_ids(self):
        directory=self.base/'artifact-recipes';directory.mkdir()
        (directory/'a.csv').write_text('recipe_id,result,ingredient,quantity\n1,foo-2,foo-1,2\n')
        (directory/'b.csv').write_text('recipe_id,result,ingredient,quantity\n1,bar-2,bar-1,3\n')
        (directory/'c.csv').write_text((directory/'a.csv').read_text())
        recipes=load_recipes(self.base)
        self.assertEqual(len(recipes),2)
        self.assertEqual(recipes.recipe_id.nunique(),2)
        (directory/'c.csv').write_text('recipe_id,result,ingredient,quantity\n1,foo-2,foo-1,4\n')
        with self.assertRaisesRegex(ValueError,'Conflicting'):load_recipes(self.base)

    def test_optimizer_selects_profile_preserves_inventory_and_exports_targets(self):
        pd.DataFrame([dict(ship='test',target='none',material_id='raw',expectation_per_launch=1),
                      dict(ship='test',target='ankh',material_id='raw',expectation_per_launch=4)]).to_csv(self.base/'ship_material_expectations.csv',index=False)
        result=self.run_plan({'metronome-4':2},fuel=20,days=1/24,parallel=1,polish_seconds=2)
        self.assertEqual(result['craft_plan'].set_index('material_id').loc['metronome-4','crafts'],1)
        self.assertEqual(result['schedule'].ship.tolist(),['test'])
        self.assertEqual(result['schedule'].target.tolist(),['ankh'])
        self.assertEqual(result['launch_plan'].target.tolist(),['ankh'])
        self.assertIn('Total achievable metronome-4: 3',result['log'])
        html=(result['out']/'plan.html').read_text()
        self.assertIn('Target: ${esc(targetNameFor(r))}',html)
        self.assertIn("'|target:'+r.target",html)
        self.assertIn('JSON.stringify([r.ship,r.target',html)
        self.assertIn('<th>Target</th>',html)

    @unittest.skipUnless(shutil.which('node'),'Node required for dashboard behavior test')
    def test_targets_not_merged_and_progress_identity_includes_target(self):
        pd.DataFrame([(1,'metronome-4','raw-a',1),(1,'metronome-4','raw-b',1)],columns=['recipe_id','result','ingredient','quantity']).to_csv(self.base/'reggference.csv',index=False)
        rows=[]
        for target,values in [('none',[0,0]),('ankh',[1,0]),('meteorite',[0,1])]:
            for material,value in zip(['raw-a','raw-b'],values):rows.append(dict(ship='test',target=target,material_id=material,expectation_per_launch=value))
        pd.DataFrame(rows).to_csv(self.base/'ship_material_expectations.csv',index=False)
        result=self.run_plan(polish_seconds=2)
        self.assertEqual(set(result['schedule'].target),{'ankh','meteorite'})
        html=(result['out']/'plan.html').read_text()
        script=r"""
const vm=require('vm'),fs=require('fs'),assert=require('assert');const html=fs.readFileSync(0,'utf8');
const nodes={};const element=()=>({value:'',innerHTML:'',textContent:'',addEventListener(){},appendChild(){},scrollIntoView(){}});
const document={getElementById(id){return nodes[id]??=element()},createElement:element,addEventListener(){},querySelectorAll(){return []}};
const context=vm.createContext({document,localStorage:{getItem(){return null},setItem(){}},console});
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
assert.equal((nodes.ships.innerHTML.match(/<article/g)||[]).length,2);
assert(nodes.lanes.innerHTML.includes('Target: ankh'));assert(nodes.lanes.innerHTML.includes('Target: meteorite'));
assert(nodes.scheduleRows.innerHTML.includes('meteorite'));
assert(vm.runInContext("missionKey({...sched[0],target:'ankh'})!==missionKey({...sched[0],target:'meteorite'})",context));
assert(vm.runInContext("missionKey({...sched[0],target:'none'})===missionKey({...sched[0],target:undefined})",context));
"""
        run=subprocess.run(['node','-e',script],input=html,text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)

    def test_profile_duplicates_and_negative_values_rejected(self):
        mission=pd.read_csv(self.base/'mission.csv').set_index('ship')
        bad=pd.DataFrame([dict(ship='test',target='none',material_id='raw',expectation_per_launch=1)]*2)
        file=self.base/'custom.csv';bad.to_csv(file,index=False)
        with self.assertRaisesRegex(ValueError,'Duplicate'):expand_profiles(mission,bad,file)
        bad=bad.iloc[:1].copy();bad['expectation_per_launch']=-1
        with self.assertRaisesRegex(ValueError,'nonnegative'):expand_profiles(mission,bad,file)
        bad['expectation_per_launch']='invalid'
        with self.assertRaisesRegex(ValueError,'numeric'):expand_profiles(mission,bad,file)
        bad['expectation_per_launch']=1;bad['status']='unobserved'
        with self.assertRaisesRegex(ValueError,'disagree'):expand_profiles(mission,bad,file)
        bad=bad.drop(columns='status')
        bad['expectation_per_launch']=1;bad['target']=''
        with self.assertRaisesRegex(ValueError,'identifiers'):expand_profiles(mission,bad,file)

    def test_metadata_hash_mismatch_and_unusable_profiles_do_not_fall_back(self):
        mission=pd.read_csv(self.base/'mission.csv').set_index('ship')
        drops=pd.read_csv(self.base/'ship_material_expectations.csv');file=self.base/'custom.csv';drops.to_csv(file,index=False)
        metadata=file.with_suffix('.metadata.json');metadata.write_text(json.dumps({'csv_sha256':'bad'}))
        with self.assertRaisesRegex(ValueError,'do not match'):expand_profiles(mission,drops,file)
        metadata.write_text(json.dumps({'profiles':[dict(ship='test',target='none',usable=False,target_name='Untargeted')]}))
        with self.assertRaisesRegex(ValueError,'No usable'):expand_profiles(mission,drops,file)

    def test_dominance_keeps_complementary_targets_and_unknowns_uncredited(self):
        options=['test','test::ankh','test::meteorite','other']
        mission=pd.DataFrame({'base_ship':['test','test','test','other']},index=options)
        rows=[]
        for option,values in zip(options,[[2,0],[3,0],[0,1],[1,0]]):
            for material,value in zip(['a','b'],values):
                rows.append(dict(ship=option,material_id=material,expectation_per_launch=value))
        retained=prune_dominated_options(options,mission,pd.DataFrame(rows),{'a','b'})
        self.assertEqual(retained,['test::ankh','test::meteorite','other'])

    def test_profile_parameters_are_shared_by_targets(self):
        mission=pd.read_csv(self.base/'mission.csv').set_index('ship')
        drops=pd.DataFrame([dict(ship='test',target=t,material_id='raw',expectation_per_launch=1) for t in ['none','ankh']])
        file=self.base/'custom.csv';drops.to_csv(file,index=False)
        file.with_suffix('.metadata.json').write_text(json.dumps({'mission_parameters':{'test':{'duration_hours':2,'capacity':10}}}))
        expanded,_,_=expand_profiles(mission,drops,file)
        self.assertEqual(set(expanded.duration),{'2.0h'})
        self.assertEqual(set(expanded.curiousity),{1})
        self.assertEqual(set(expanded.base_ship),{'test'})


if __name__=='__main__':unittest.main()
