"""Compare a checkout or historical optimizer on identical inventory-aware cases."""
import argparse
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
    parser.add_argument('--solver-seconds',type=float,default=10)
    parser.add_argument('--polish-seconds',type=float,default=5)
    parser.add_argument('--wall-seconds',type=float,default=40)
    args=parser.parse_args()
    folder=ROOT/'results/quality-comparison'/f'{args.label}-{time.time_ns()}'
    folder.mkdir(parents=True)
    records=[]
    for days in [26,30,100]:
        output=folder/str(days)
        command=[sys.executable,'-u',str(args.optimizer.resolve()),'--data-dir',str(ROOT/'data'),
                 '--target','metronome-4','--days',str(days),'--fuel','500','--parallel','3','--events','1',
                 '--sleep','00:00-11:00','--max-launches-per-hour','2','--inventory',str(ROOT/'data/inventory.csv'),
                 '--solver-seconds',str(args.solver_seconds),'--polish-seconds',str(args.polish_seconds),'--output-dir',str(output)]
        started=time.perf_counter()
        with (folder/f'{days}.log').open('w') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,
                env=dict(os.environ,PYTHONPATH=str(ROOT),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
            try:code=process.wait(timeout=args.wall_seconds)
            except subprocess.TimeoutExpired:process.kill();process.wait();code='wall_timeout'
        records.append({'days':days,'wall_seconds':time.perf_counter()-started,'exit_code':code})
        (folder/'measurements.json').write_text(json.dumps(records,indent=2)+'\n')
        print(records[-1],flush=True)
    print('Artifacts:',folder)


if __name__=='__main__':main()
