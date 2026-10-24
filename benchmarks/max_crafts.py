#!/usr/bin/env python3
"""Compare search modes with all ships/targets and the requested 360-launch cap."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cases',nargs='*');options=parser.parse_args()
    records=[]
    for seconds in [30,120,300]:
        for mode in ['balanced','max-crafts']:
            case=f'{mode}-{seconds}'
            if options.cases and case not in options.cases:continue
            output=ROOT/'results'/'max-crafts-benchmark'/case;output.mkdir(parents=True,exist_ok=True)
            metadata=output/'plan_metadata.json'
            if metadata.exists():metadata.unlink()
            command=[sys.executable,str(ROOT/'optimize_reggference.py'),'--mode',mode,'--target','ankh-4',
                     '--days','30','--fuel','500','--parallel','3','--events','1','--event-hours','48',
                     '--event-multiplier','2','--sleep','00:00-11:00','--max-launches-per-hour','2',
                     '--max-total-launches','360','--max-launches-per-day','0','--inventory',str(ROOT/'data/inventory.csv'),
                     '--solver-seconds',str(seconds),'--polish-seconds','2','--output-dir',str(output)]
            started=time.monotonic();code=None;timeout=False
            with (output/'run.log').open('w') as stream:
                try:code=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=seconds+20).returncode
                except subprocess.TimeoutExpired:timeout=True
            record=dict(case=case,mode=mode,solver_seconds=seconds,requested_polish_seconds=2,wall_seconds=time.monotonic()-started,exit_code=code,outer_timeout=timeout,command=command)
            if code==0 and metadata.exists():
                meta=json.loads(metadata.read_text());opt=meta['optimization'];proof=opt['guarantees']
                record.update(crafts=proof['crafts']['value'],upper_bound=proof['crafts']['bound'],gap=proof['crafts']['gap'],
                              launches=proof['launch_count']['value'],allocated_fuel=proof['allocated_fuel']['value'],
                              completion_day=proof['completion']['value']/24,status=opt['message'],guarantees=proof,
                              timing=opt['timing'],solver_runs=opt['solver_runs'],craft_search=opt.get('craft_search',[]))
                with (output/'fuel_allocation.csv').open() as stream:record['consumed_fuel']=sum(float(r['used_T']) for r in csv.DictReader(stream))
            records.append(record)
            (ROOT/'benchmarks/max_crafts.json').write_text(json.dumps(records,indent=2)+'\n')
            print(json.dumps({k:v for k,v in record.items() if k not in ['command','guarantees','solver_runs','craft_search']}),flush=True)

if __name__=='__main__':main()
