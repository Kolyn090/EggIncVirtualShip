#!/usr/bin/env python3
"""Reproducible full-targeting runtime/launch-effort benchmark; no stale outputs."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
CASES=[('unlimited-5',5,0,0),('unlimited-30',30,0,0),('unlimited-120',120,0,0),
       ('cap20-30',30,20,0),('cap40-30',30,40,0),('cap60-30',30,60,0),('daily3-cap40-30',30,40,3)]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cases',nargs='*');parser.add_argument('--output',default='benchmarks/runtime_and_effort.json')
    options=parser.parse_args();records=[]
    for name,seconds,cap,daily in CASES:
        if options.cases and name not in options.cases:continue
        output=ROOT/'results'/'runtime-effort'/name
        output.mkdir(parents=True,exist_ok=True)
        metadata=output/'plan_metadata.json'
        if metadata.exists():metadata.unlink()
        command=[sys.executable,str(ROOT/'optimize_reggference.py'),'--target','ankh-4','--days','30','--fuel','500',
                 '--events','1','--event-hours','48','--sleep','00:00-11:00','--max-launches-per-hour','2',
                 '--max-total-launches',str(cap),'--max-launches-per-day',str(daily),'--inventory',str(ROOT/'data/inventory.csv'),
                 '--solver-seconds',str(seconds),'--polish-seconds','2','--output-dir',str(output)]
        started=time.monotonic();timed_out=False
        with (output/'run.log').open('w') as log:
            try:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=seconds+20)
            except subprocess.TimeoutExpired:result=None;timed_out=True
        record=dict(case=name,solver_seconds=seconds,polish_seconds=2,max_total_launches=cap,max_launches_per_day=daily,
                    wall_seconds=time.monotonic()-started,exit_code=result.returncode if result else None,outer_timeout=timed_out,
                    command=command)
        if metadata.exists() and not timed_out:
            data=json.loads(metadata.read_text());opt=data['optimization'];proof=opt['guarantees']
            record.update(crafts=proof['crafts']['value'],bound=proof['crafts']['bound'],gap=proof['crafts']['gap'],
                          launches=proof['launch_count']['value'],allocated_fuel=proof['allocated_fuel']['value'],
                          completion_day=proof['completion']['value']/24,status=opt['message'],guarantees=proof,timing=opt['timing'],solver_runs=opt['solver_runs'])
            with (output/'fuel_allocation.csv').open() as stream:record['consumed_fuel']=sum(float(row['used_T']) for row in csv.DictReader(stream))
        records.append(record)
        Path(options.output).write_text(json.dumps(records,indent=2)+'\n')
        print(json.dumps({k:v for k,v in record.items() if k not in ['command','guarantees','solver_runs']}),flush=True)

if __name__=='__main__':main()
