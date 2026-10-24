"""Run isolated optimizer processes; retain logs, measurements, and plan outputs."""
import argparse
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--optimizer',type=Path,default=ROOT/'optimize_reggference.py')
    parser.add_argument('--label',default='current')
    parser.add_argument('--solver-seconds',type=float,default=5)
    parser.add_argument('--wall-seconds',type=float,default=20)
    parser.add_argument('--days',type=int,nargs='+',default=[26,100])
    parser.add_argument('--rates',type=int,nargs='+',default=[0,2])
    args=parser.parse_args()
    destination=ROOT/'results/performance'/f'{args.label}-{time.time_ns()}'
    destination.mkdir(parents=True)
    records=[]
    for days,sleep,limit in itertools.product(args.days,[False,True],args.rates):
        name=f'{days}-sleep{int(sleep)}-limit{limit}'
        output=destination/name
        command=[sys.executable,'-u',str(args.optimizer.resolve()),'--data-dir',str(ROOT/'data'),
                 '--days',str(days),'--events','1','--fuel','500','--solver-seconds',str(args.solver_seconds),
                 '--max-launches-per-hour',str(limit),'--output-dir',str(output)]
        if sleep:command+=['--sleep','23:00-08:00']
        started=time.perf_counter()
        with (destination/f'{name}.log').open('w') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,
                      env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONPATH=str(ROOT)))
            try:code=process.wait(timeout=args.wall_seconds)
            except subprocess.TimeoutExpired:
                process.kill();process.wait();code='wall_timeout'
        record={'case':name,'wall_seconds':round(time.perf_counter()-started,3),'exit_code':code}
        metadata=output/'plan_metadata.json'
        if code==0 and metadata.exists():record['optimization']=json.loads(metadata.read_text()).get('optimization')
        records.append(record)
        (destination/'measurements.json').write_text(json.dumps(records,indent=2)+'\n')
        print(record,flush=True)
    print('Artifacts:',destination)


if __name__=='__main__':main()
