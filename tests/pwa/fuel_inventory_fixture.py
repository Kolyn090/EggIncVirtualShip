"""Generate an actual fixed-fuel optimizer export for offline browser tests."""
import contextlib
import io
from argparse import Namespace
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))


def main():
    from optimize_reggference import solve
    base=Path(sys.argv[1])/'fixed-fuel-inputs';base.mkdir()
    (base/'mission.csv').write_text('ship,duration,curiousity,kindness,resilence,integrity,humility\nhenerprise-1,9h36m,15,10,0,0,10\n')
    (base/'ship_material_expectations.csv').write_text('ship,target,material_id,expectation_per_launch\nhenerprise-1,ankh,raw,1\n')
    (base/'reggference.csv').write_text('recipe_id,result,ingredient,quantity\n1,ankh-4,raw,1\n')
    output=base/'results'
    args=Namespace(data_dir=str(base),expectations='ship_material_expectations.csv',ships=None,inventory=None,
                   target='ankh-4',days=1,parallel=3,events=0,event_hours=1,event_multiplier=2,sleep=[],no_launch=[],
                   fuel=0,fuel_step=5,fuel_mode='existing_inventory',initial_fuel=['curiosity=45.5T','kindness=30T','humility=30T'],
                   mode='balanced',max_launches_per_hour=1,max_total_launches=3,max_launches_per_day=0,
                   solver_seconds=6,polish_seconds=1,output_dir=str(output))
    with contextlib.redirect_stdout(io.StringIO()):solve(args)
    shutil.copyfile(output/'plan.html',Path(sys.argv[1])/'fuel-inventory.html')


if __name__=='__main__':main()
