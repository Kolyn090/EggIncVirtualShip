"""Recipe discovery and validated ship/target option expansion."""
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


def load_recipes(base):
    directory=base/'artifact-recipes'
    files=sorted(directory.glob('*.csv')) if directory.is_dir() else [base/'reggference.csv']
    if not files:raise ValueError('No recipe CSV files found in '+str(directory))
    seen={};frames=[]
    for file in files:
        frame=pd.read_csv(file)
        if not {'recipe_id','result','ingredient','quantity'}<=set(frame.columns):raise ValueError('Invalid recipe columns in '+str(file))
        if frame.recipe_id.isna().any():raise ValueError('Missing recipe ID in '+str(file))
        for rid,group in frame.groupby('recipe_id',sort=False):
            if group.result.nunique()!=1 or group.result.isna().any() or group.ingredient.isna().any():raise ValueError('Invalid recipe in '+str(file))
            qty=pd.to_numeric(group.quantity,errors='coerce')
            if not np.isfinite(qty).all() or (qty<=0).any():raise ValueError('Invalid recipe quantities in '+str(file))
            result=group.result.iloc[0];signature=tuple(sorted(zip(group.ingredient,qty)))
            if result in seen:
                if seen[result]!=signature:raise ValueError(f'Conflicting recipes for {result} in {file}')
                continue
            seen[result]=signature;group=group.copy();group['quantity']=qty
            group['recipe_id']=f'{file.name}::{rid}';frames.append(group)
    if not frames:raise ValueError('No craftable recipes found')
    return pd.concat(frames,ignore_index=True)


def expand_profiles(mission, drops, csv_path):
    """Internal option keys never leak into public ship IDs or mission duration."""
    meta_path=csv_path.with_suffix('.metadata.json')
    metadata=json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if metadata.get('csv_sha256') and hashlib.sha256(csv_path.read_bytes()).hexdigest()!=metadata['csv_sha256']:
        raise ValueError('Expectation CSV and provenance metadata do not match; regenerate the data')
    if not {'ship','material_id','expectation_per_launch'}<=set(drops.columns):
        raise ValueError('Expectation CSV requires ship, material_id and expectation_per_launch columns')
    drops=drops.copy()
    if 'target' not in drops:drops['target']='none'
    if drops.target.isna().any() or not drops.target.map(lambda x:bool(re.fullmatch(r'[a-z][a-z0-9-]*',str(x)))).all():
        raise ValueError('Mission targeting identifiers must be nonempty family IDs, or none')
    if drops.duplicated(['ship','target','material_id']).any():raise ValueError('Duplicate rates for ship, target and material')
    raw=pd.to_numeric(drops.expectation_per_launch,errors='coerce')
    if (drops.expectation_per_launch.notna() & raw.isna()).any():
        raise ValueError('Drop expectations must be numeric or blank for explicit unknown supply')
    known=raw.notna()
    if not np.isfinite(raw[known]).all() or (raw[known]<0).any():raise ValueError('Known drop expectations must be finite and nonnegative')
    if 'status' in drops:
        statuses={'empirical','confirmed_zero','unobserved','unknown_profile'}
        if not drops.status.isin(statuses).all():raise ValueError('Unknown expectation status')
        if (known != drops.status.isin({'empirical','confirmed_zero'})).any():
            raise ValueError('Expectation status and numeric/unknown value disagree')
        if (raw[drops.status=='confirmed_zero']!=0).any():raise ValueError('Confirmed zero must have expectation zero')
    catalog={(p['ship'],p['target']):p for p in metadata.get('profiles',[])}
    if catalog:
        invalid={(s,t) for s,t in zip(drops.ship,drops.target) if (s,t) not in catalog}
        if invalid:raise ValueError('Expectation CSV contains unsupported ship/target profiles: '+str(sorted(invalid)))
        keep=[catalog[(s,t)]['usable'] for s,t in zip(drops.ship,drops.target)]
        drops=drops.loc[keep].copy()
    options=[];names={'none':'Untargeted'}
    for (ship,target),group in drops.groupby(['ship','target'],sort=True):
        if ship not in mission.index:continue
        key=ship if target=='none' else f'{ship}::{target}'
        row=mission.loc[ship].copy();row.name=key;row['base_ship']=ship;row['drop_target']=target
        params=metadata.get('mission_parameters',{}).get(ship)
        if params:
            row['duration']=str(float(params['duration_hours']))+'h'
            row['capacity']=params['capacity']
        options.append(row)
        if catalog:names[target]=catalog[(ship,target)]['target_name']
    if not options:raise ValueError('No usable ship/target profiles; generate validated data or supply a matching expectations file')
    expanded=pd.DataFrame(options);expanded.index.name='ship'
    drops['base_ship']=drops.ship
    drops['ship']=[ship if target=='none' else f'{ship}::{target}' for ship,target in zip(drops.ship,drops.target)]
    info={'assumptions':metadata.get('assumptions'), 'source_hashes':metadata.get('source_hashes'),
          'csv_sha256':metadata.get('csv_sha256'),'shared_lib_commit':metadata.get('shared_lib_commit'),
          'recipe_warnings':metadata.get('recipe_warnings',[]),'target_names':names,
          'excluded_profiles':sum(not p['usable'] for p in catalog.values()),
          'supply_policy':'Known empirical point estimates and confirmed structural zeros only; unknown supply is uncredited, not measured zero'}
    return expanded,drops,info


def prune_dominated_options(available,mission,drops,materials):
    """Same-ship targeting options have identical timing/cost; use Pareto dominance."""
    rates=drops.pivot(index='ship',columns='material_id',values='expectation_per_launch').apply(pd.to_numeric,errors='coerce').fillna(0)
    rates=rates.reindex(index=available,columns=sorted(materials),fill_value=0).fillna(0)
    useful=[option for option in available if (rates.loc[option]>0).any()]
    if not useful:return available[:1]
    retained=[]
    for option in useful:
        vector=rates.loc[option].to_numpy()
        base=mission.loc[option,'base_ship']
        dominated=False
        for other in useful:
            if option==other or mission.loc[other,'base_ship']!=base:continue
            alternative=rates.loc[other].to_numpy()
            if (alternative>=vector).all() and ((alternative>vector).any() or other<option):
                dominated=True;break
        if not dominated:retained.append(option)
    return retained
