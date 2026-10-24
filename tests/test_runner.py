import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class RunnerTests(unittest.TestCase):
    def test_arguments_paths_overrides_and_exit_status(self):
        with tempfile.TemporaryDirectory(prefix='optimizer space ') as directory:
            root=Path(directory)
            script=(ROOT/'run_optimizer.sh').read_text().replace('SLEEP_WINDOWS=("23:00-08:00")','SLEEP_WINDOWS=("23:00-08:00" "12:00-13:00")').replace('NO_LAUNCH_WINDOWS=()','NO_LAUNCH_WINDOWS=("2-3" "4-5")')
            (root/'run_optimizer.sh').write_text(script)
            (root/'.venv/bin').mkdir(parents=True)
            fake=root/'.venv/bin/python'
            fake.write_text('#!'+sys.executable+'\nimport json,sys,os\nprint(json.dumps({"cwd":os.getcwd(),"args":sys.argv[1:]}))\nsys.exit(int(os.environ.get("RUNNER_TEST_EXIT","0")))\n')
            fake.chmod(0o755)
            command=['bash',str(root/'run_optimizer.sh'),'--target','ankh-4','--days','30','--inventory','inventory with spaces.csv']
            run=subprocess.run(command,cwd='/tmp',text=True,capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            data=json.loads(run.stdout);args=data['args']
            self.assertEqual(data['cwd'],str(root))
            self.assertEqual(args[0],str(root/'optimize_reggference.py'))
            self.assertEqual(args[args.index('--output-dir')+1],'results/ankh-4')
            self.assertEqual(args.count('--sleep'),2)
            self.assertEqual(args.count('--no-launch'),2)
            self.assertEqual(args[-1],'inventory with spaces.csv')
            self.assertEqual(args[-5:-3],['ankh-4','--days'])
            (root/'run_optimizer.sh').write_text(script.replace('TARGET="metronome-4"','TARGET="ankh-4"'))
            configured=subprocess.run(['bash',str(root/'run_optimizer.sh')],cwd='/tmp',capture_output=True,text=True)
            configured_args=json.loads(configured.stdout)['args']
            self.assertEqual(configured_args[configured_args.index('--target')+1],'ankh-4')
            failed=subprocess.run(command,env=dict(os.environ,RUNNER_TEST_EXIT='7'),capture_output=True)
            self.assertEqual(failed.returncode,7)

    def test_real_targets_inventory_and_errors(self):
        inventory=ROOT/'data/inventory.csv'
        original=inventory.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for target in ['metronome-4','ankh-4']:
                inv=root/'owned.csv'
                material='metronome-3' if target=='metronome-4' else 'ankh-3'
                raw='geode-3' if target=='metronome-4' else 'meteorite-3'
                inv.write_text(f'material_id,quantity\n{material},72\n{raw},4\n{target},2\n')
                out=root/target
                command=[str(ROOT/'run_optimizer.sh'),'--target',target,'--days','30','--events','0','--fuel','0','--ships','henerprise-1','--inventory',str(inv),'--output-dir',str(out)]
                run=subprocess.run(command,cwd='/tmp',text=True,capture_output=True)
                self.assertEqual(run.returncode,0,run.stderr)
                self.assertIn(f'Total achievable {target}: 3',run.stdout)
                meta=json.loads((out/'plan_metadata.json').read_text())
                self.assertEqual(meta['target'],target)
                html=(out/'plan.html').read_text()
                self.assertIn('"target": "'+target+'"',html)
                self.assertIn("'reggference-done-v2-'+targetId+'-'",html)
                with (out/'craft_plan.csv').open() as stream:
                    crafts=list(csv.DictReader(stream))
                self.assertEqual({r['material_id'] for r in crafts},{target})
            for content in [None,'material_id,quantity\nankh-4,-1\n']:
                path=root/'bad.csv'
                if content is not None:path.write_text(content)
                run=subprocess.run([str(ROOT/'run_optimizer.sh'),'--inventory',str(path)],capture_output=True,text=True)
                self.assertEqual(run.returncode,2)
                self.assertIn('inventory',run.stderr.lower())
            run=subprocess.run([str(ROOT/'run_optimizer.sh'),'--target','bogus'],capture_output=True,text=True)
            self.assertEqual(run.returncode,2)
            self.assertIn('Unknown crafting target',run.stderr)
        self.assertEqual(inventory.read_bytes(),original)

if __name__=='__main__':unittest.main()
