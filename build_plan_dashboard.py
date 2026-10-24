#!/usr/bin/env python3
"""Build a self-contained, offline HTML dashboard from Reggference optimizer CSV outputs."""
import argparse
import csv
import json
from pathlib import Path
from schedule_validation import validate_schedule

REQUIRED = ('launch_plan.csv', 'schedule.csv', 'craft_plan.csv', 'material_balance.csv', 'event_windows.csv')

def read_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def describe_gap(start, end, restrictions, events=(), next_boost=False):
    """Partition a gap into disjoint intervals; never classify by any overlap."""
    points={start,end}
    for window in [*restrictions,*events]:
        a=float(window['start_hour']);b=float(window['end_hour'])
        if a<end and b>start:points.update([max(a,start),min(b,end)])
    next_event=next((float(w['start_hour']) for w in events
                     if float(w['start_hour'])<=end<float(w['end_hour'])),None) if next_boost else None
    segments=[];totals={}
    for a,b in zip(sorted(points),sorted(points)[1:]):
        if b-a<=1e-8:continue
        mid=(a+b)/2
        kinds=sorted({w.get('kind','unclassified-blackout') for w in restrictions
                      if float(w['start_hour'])<=mid<float(w['end_hour'])})
        kind='+'.join(kinds) if kinds else ('event-wait' if next_event is not None and mid<next_event else 'idle')
        totals[kind]=totals.get(kind,0.)+b-a
        if segments and segments[-1]['kind']==kind:segments[-1]['end_hour']=b
        else:segments.append({'start_hour':a,'end_hour':b,'kind':kind})
    return {'start_hour':start,'end_hour':end,'hours':end-start,'segments':segments,'totals':totals}


def build(results: Path, output: Path):
    missing = [n for n in REQUIRED if not (results / n).is_file()]
    if missing:
        raise SystemExit('Missing optimizer results: ' + ', '.join(missing) + f' in {results}')
    data = {n.replace('.csv',''):read_rows(results / n) for n in REQUIRED}
    data['fuel_allocation']=read_rows(results/'fuel_allocation.csv') if (results/'fuel_allocation.csv').exists() else None
    data['sleep_windows'] = read_rows(results/'sleep_windows.csv') if (results/'sleep_windows.csv').exists() else []
    detailed=results/'launch_restrictions.csv'
    restrictions=read_rows(detailed) if detailed.exists() else [dict(w,kind='unclassified-blackout') for w in data['sleep_windows']]
    data['launch_restrictions']=restrictions
    events=[w for w in data['event_windows'] if str(w['event_bonus']).lower()=='true']
    previous={}
    for row in sorted(data['schedule'],key=lambda r:(float(r['start_hour']),int(r['slot']))):
        slot=row['slot'];start=float(row['start_hour'])
        if slot in previous and start>previous[slot]+1/60:
            row['gap_before']=describe_gap(previous[slot],start,restrictions,events,str(row['event_bonus']).lower()=='true')
        previous[slot]=float(row['end_hour'])
    metadata=results/'plan_metadata.json'
    data['metadata']=json.loads(metadata.read_text(encoding='utf-8')) if metadata.exists() else {'target':'metronome-4'}
    validate_schedule(data['schedule'],int(data['metadata'].get('max_launches_per_hour',0)),
                      data['metadata'].get('horizon_hours'),max_slots=data['metadata'].get('parallel'),
                      event_windows=[(float(w['start_hour']),float(w['end_hour']),str(w['event_bonus']).lower()=='true') for w in data['event_windows']],
                      blackouts=[(float(w['start_hour']),float(w['end_hour'])) for w in data['sleep_windows']])
    data['summary']={
        'completion_hour':max((float(r['end_hour']) for r in data['schedule']),default=0.),
        'allocated_fuel_T':sum(float(r['allocated_T']) for r in data['fuel_allocation']) if data['fuel_allocation'] is not None else None,
        'consumed_fuel_T':sum(float(r['total_fuel_T']) for r in data['launch_plan']),
        'launches':len(data['schedule'])}
    blob = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    html = TEMPLATE.replace('/*__DATA__*/', blob)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding='utf-8')
    print('Dashboard:', output.resolve())

TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reggference • Mission Plan</title>
<style>
:root{color-scheme:dark;--bg:#0a1222;--panel:#111e32;--panel2:#17263c;--border:#2a3b50;--ink:#edf4ff;--muted:#9aacc3;--accent:#58d3b4;--gold:#f3bd66;--blue:#77adfa}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 70% -10%,#1a3150 0%,var(--bg) 62%);color:var(--ink);font:14px/1.5 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}main{max-width:1380px;margin:auto;padding:30px 30px 65px}h1{font-size:29px;letter-spacing:-.8px;margin:0}h2{font-size:18px;margin:0}p{margin:6px 0;color:var(--muted)}.eyebrow{text-transform:uppercase;letter-spacing:2px;font-size:11px;font-weight:800;color:var(--accent)}.head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:24px;flex-wrap:wrap}.tag{border:1px solid var(--border);padding:8px 12px;border-radius:12px;color:var(--muted)}.stats{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:13px;margin-bottom:23px}.stat,.panel{background:var(--panel);border:1px solid var(--border);border-radius:16px}.stat{padding:18px}.stat .k{color:var(--muted);font-size:12px}.stat strong{display:block;font-size:27px;margin-top:4px;letter-spacing:-.7px}.stat small{color:var(--muted)}.section{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:27px 0 13px;flex-wrap:wrap}.section small,.sub{color:var(--muted)}.panel{padding:18px}.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center}select,input{background:#0b172a;color:var(--ink);border:1px solid var(--border);padding:9px 12px;border-radius:9px;font:inherit}input{min-width:180px}.button{background:#193b42;border:1px solid #33796c;color:#bdffed;padding:8px 14px;border-radius:9px;cursor:pointer;font:inherit}.button:hover{filter:brightness(1.2)}.shipgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}.shipcard{background:var(--panel);border:1px solid var(--border);padding:14px;border-radius:13px}.shipcard .name{font-weight:750;font-size:15px}.shipcard .num{font-size:24px;font-weight:750}.shipcard .mini{display:flex;justify-content:space-between;margin-top:4px;color:var(--muted)}.eventpill{border-radius:100px;background:#55401f;color:#ffda91;font-size:11px;padding:3px 9px;margin-left:7px;white-space:nowrap}.timelinewrap{overflow:auto}.timeline{min-width:730px}.axis,.lane{display:grid;grid-template-columns:90px minmax(640px,1fr);gap:12px}.axis{margin-bottom:8px}.ticks{height:25px;position:relative;border-bottom:1px solid var(--border)}.tick{position:absolute;top:0;font-size:11px;transform:translateX(-50%);color:var(--muted)}.tick:first-child{transform:none}.lane{margin-bottom:9px}.label{color:var(--muted);font-size:12px;padding-top:11px;font-weight:700}.track{height:42px;position:relative;background:#0a1728;border:1px solid var(--border);border-radius:8px;overflow:hidden}.window{position:absolute;height:100%;background:#9a6d30;opacity:.23}.gridline{position:absolute;height:100%;border-left:1px solid #344257;opacity:.5}.mission{position:absolute;height:29px;top:6px;border-radius:4px;background:#4b86bb;border:1px solid #86bef2;opacity:.95;overflow:hidden;white-space:nowrap;font-size:11px;line-height:27px;padding:0 5px;color:#fff;cursor:help}.mission.boost{background:#a67939;border-color:#e9bd6f}.mission:hover{filter:brightness(1.35);z-index:3}.legend{display:flex;gap:17px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:13px}.swatch{display:inline-block;width:11px;height:11px;border-radius:3px;background:#4b86bb;margin-right:5px}.swatch.b{background:#a67939}.swatch.e{background:#9a6d30}.note{font-size:12px;color:var(--muted);margin-top:12px}.twocol{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px}.progress{height:9px;background:#0a1728;border-radius:50px;margin:7px 0 15px;overflow:hidden}.progress div{height:100%;background:var(--accent);border-radius:50px}.fuelrow{display:flex;justify-content:space-between;gap:10px;margin-top:9px}.tablewrap{overflow:auto;max-height:480px}table{width:100%;border-collapse:collapse;text-align:left;white-space:nowrap}th{background:var(--panel);position:sticky;top:0;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.8px}td,th{padding:10px 12px;border-bottom:1px solid var(--border)}td.numeric,th.numeric{text-align:right;font-variant-numeric:tabular-nums}.good{color:var(--accent)}.warn{color:var(--gold)}.empty{padding:20px;color:var(--muted)}.foot{margin-top:25px;color:var(--muted);font-size:12px}@media(max-width:740px){main{padding:16px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.twocol{grid-template-columns:minmax(0,1fr)}h1{font-size:25px}}

.timelinewrap{overflow:hidden;min-width:0;max-width:100%}.timeline-list{display:grid;gap:18px;min-width:0;max-width:100%}.checklane{border:1px solid var(--border);background:#0b1729;border-radius:14px;padding:14px;min-width:0;max-width:100%;overflow:hidden}.lane-header{display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap}.lane-header strong{font-size:15px}.lane-header small{color:var(--muted)}.mission-scroll{display:flex;width:100%;max-width:100%;min-width:0;overflow-x:auto;overflow-y:hidden;overscroll-behavior-x:contain;gap:9px;padding:4px 2px 14px;scrollbar-width:thin;scrollbar-color:#587086 #112236;min-height:132px}.mission-cell{font:inherit;text-align:left;flex:0 0 164px;min-height:134px;background:#183a5b;border:1px solid #478ac6;border-radius:12px;color:var(--ink);padding:11px 12px;cursor:pointer;display:flex;flex-direction:column;justify-content:space-between;position:relative;transition:background .15s,transform .15s}.mission-cell:hover{filter:brightness(1.17);transform:translateY(-2px)}.mission-cell:focus-visible{outline:3px solid var(--accent);outline-offset:2px}.mission-cell.boost{background:#5a4225;border-color:#d8a75b}.mission-cell.done{background:#16463a;border:2px solid #65d9b0}.mission-cell.next-up{outline:2px solid #ffdb81;outline-offset:2px}.mission-cell.done::after{content:'✓';position:absolute;right:10px;top:7px;font-weight:900;font-size:21px;color:#9affe0}.mission-cell .mission-name{display:block;font-size:13px;font-weight:800;line-height:1.35;padding-right:13px;overflow-wrap:anywhere}.mission-cell .mission-time{font-size:11px;color:#d1e0ee}.mission-cell .mission-flag{font-size:11px;opacity:.92}.lane-gap{display:flex;align-items:center;justify-content:center;flex:0 0 110px;background:#142034;color:#b9c8db;border:1px dashed #52708a;border-radius:10px;font-size:11px;text-align:center;padding:9px}.lane-gap.sleep{border-color:#866d97;color:#dec9ea;background:#2d2139}.mission-progress{height:7px;border-radius:6px;background:#2c3d53;overflow:hidden;flex:1;max-width:250px}.mission-progress>div{height:100%;background:#58d3b4}.swatch.done-swatch{background:#24785d}.swatch.sleeping{background:#624375}.table-done{background:#1c5546;color:#a9ffe3;border-radius:8px;padding:5px 10px;cursor:pointer;border:1px solid #58cda8}.table-undone{background:#213853;color:#d7eaff;border-radius:8px;padding:5px 10px;cursor:pointer;border:1px solid #466586}@media(max-width:650px){.mission-cell{flex-basis:148px}.checklane{padding:10px}}
/* Keep sticky table headers inside their own scroll viewport. */
.table-panel{min-width:0;overflow:hidden;padding:0;isolation:isolate}
.table-panel .tablewrap{max-height:480px;max-width:100%;overflow:auto;position:relative;overscroll-behavior:contain}
.table-panel table{border-collapse:separate;border-spacing:0;width:100%}
.table-panel thead{position:relative;z-index:2}
.table-panel thead th{position:sticky;top:0;z-index:3;background:#17263c;box-shadow:inset 0 -1px 0 var(--border);background-clip:padding-box}
.table-panel tbody td{background:var(--panel)}
.gap-details{display:block;flex:0 0 150px;align-self:flex-start;max-height:240px;overflow:auto}.gap-details summary{cursor:pointer;padding:8px;min-height:70px}.gap-breakdown{text-align:left;max-height:170px;overflow:auto}.gap-breakdown ul{padding-left:16px}.gap-reason{display:block;padding:4px;border-left:3px solid #7091ab;margin:3px 0}.gap-reason.sleep{border-color:#b28dce;background:#2d2139}.gap-reason.no-launch{border-color:#e48d86;background:#3b2728}.gap-reason.event-wait{border-color:#e5b45d;background:#48371e}
</style></head><body><main>
<header class="head"><div><div class="eyebrow">Mission optimization / expected drops</div><h1 id="targetTitle">Crafting plan</h1><p>Understand launches, event bonuses, crafting, and remaining materials at a glance.</p></div><div><div class="tag" id="horizon"></div><div class="tag" id="launchLimit"></div><div class="tag" id="planStatus"></div><div class="tag" id="fuelStatus"></div><div class="tag" id="completionStatus"></div><div class="tag" id="completionDay"></div></div></header>
<section class="stats"><div class="stat"><div class="k">Total achievable target items</div><strong id="craftTotal">—</strong><small id="inventorySummary"></small></div><div class="stat"><div class="k">Total launches</div><strong id="launchTotal">—</strong><small id="boostTotal"></small></div><div class="stat"><div class="k">Allocated fuel</div><strong id="allocatedFuelTotal">—</strong><small id="fuelTotal"></small></div><div class="stat"><div class="k">Mission slots</div><strong id="slotTotal">—</strong><small id="eventTotal"></small></div></section>
<div class="section"><div><h2>Recommended ships</h2><small>Grouped across all three slots and planning phases</small></div><div class="filters"><input id="search" placeholder="Filter ship names" aria-label="Filter ships"><select id="boostFilter" aria-label="Filter launches"><option value="all">All launches</option><option value="boost">Boosted only</option><option value="normal">Regular only</option></select></div></div>
<div id="ships" class="shipgrid"></div><p class="note" id="zeroFuelNote"></p>
<div class="section"><div><h2>Launch checklist</h2><small>Large clickable cells ordered by launch time within each slot. Click to mark done.</small></div><div class="filters"><span class="tag" id="doneCount">0 / 0 done</span><button class="button" id="jumpProgress" type="button">Jump to next launch ↗</button><select id="slotFilter" aria-label="Timeline slot"><option value="all">All slots</option></select><button class="button" id="exportProgress">Export progress</button><button class="button" id="importProgress">Import progress</button><input type="file" id="progressFile" accept="application/json,.json" hidden></div></div>
<div class="panel timelinewrap"><div class="timeline-list" id="lanes"></div><div class="legend"><span><i class="swatch"></i>Normal</span><span><i class="swatch b"></i>2× capacity</span><span><i class="swatch done-swatch"></i>Done ✓</span><span><i class="swatch e"></i>Event</span><span><i class="swatch sleeping"></i>Sleep</span><span>◇ Explicit no-launch</span><span>○ Idle / waiting</span><span>✦ Possible event wait</span></div><p class="note">Cards show the correct launch order and start times, but widths are intentionally equal for readability (not proportional to mission duration). Missions may finish during sleep; only new launches are restricted. Completion is saved in this browser, and you can export/import your progress.</p></div>
<div class="twocol"><div><div class="section"><h2>Fuel breakdown</h2><small>Combined across all launches</small></div><div class="panel" id="fuelPanel"></div></div><div><div class="section"><h2>Crafting quantities</h2><small>Intermediate materials and final products</small></div><div class="panel" id="craftPanel"></div></div></div>
<div class="section"><div><h2>Material balance</h2><small>Starting inventory, expected drops, crafts, consumption, and remaining quantities</small></div><input id="materialSearch" placeholder="Find a material" aria-label="Filter materials"></div>
<div class="panel table-panel"><div class="tablewrap"><table><thead><tr><th>Material</th><th class="numeric">Starting inventory</th><th class="numeric">Expected drops</th><th class="numeric">Crafted</th><th class="numeric">Consumed</th><th class="numeric">Expected remaining</th></tr></thead><tbody id="materials"></tbody></table></div></div>
<div class="section"><div><h2>Full launch schedule</h2><small>Every launch, in chronological order</small></div></div>
<div class="panel table-panel"><div class="tablewrap"><table><thead><tr><th>Start</th><th>End</th><th>Slot</th><th>Ship</th><th>Target</th><th>Bonus</th><th>Done</th></tr></thead><tbody id="scheduleRows"></tbody></table></div></div>
<p class="foot">This plan uses expected drops, not guaranteed inventory. Events are hypothetical windows chosen by the optimizer. An optimal MILP solution can have alternative equally optimal schedules.</p>
</main><script>
const data=/*__DATA__*/;
document.getElementById('launchLimit').textContent=data.metadata?.max_launches_per_hour ? `Launch limit: ${data.metadata.max_launches_per_hour} per slot per rolling hour` : 'Launch limit: unlimited';
const optimization=data.metadata?.optimization;
document.getElementById('planStatus').textContent=optimization ? (optimization.status===0?'Craft maximum proven':'Feasible plan; craft maximum unproven') : 'Legacy plan: proof status unavailable';
const guarantees=optimization?.guarantees;
document.getElementById('fuelStatus').textContent=guarantees?.allocated_fuel?.proven?'Minimum allocated fuel proven (fixed craft count)':'Minimum fuel unproven';
document.getElementById('completionStatus').textContent=guarantees?.completion?.proven?'Minimum completion proven (fixed crafts/fuel)':'Minimum completion unproven';
const targetId=data.metadata?.target||'metronome-4';
const targetName=({'metronome-4':'Reggference Quantum Metronome','ankh-4':'Brilliant Tungsten Ankh'})[targetId]||targetId;
document.title=targetName+' • Mission Plan';
document.getElementById('targetTitle').textContent='Target: '+targetName;
const num=v=>Number(v)||0, fmt=(v,d=2)=>Number(v).toLocaleString(undefined,{maximumFractionDigits:d}), day=h=>`Day ${fmt(num(h)/24,2)}`, esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sched=data.schedule.map(r=>({...r,slot:num(r.slot),start_hour:num(r.start_hour),end_hour:num(r.end_hour),event_bonus:String(r.event_bonus).toLowerCase()==='true'})).sort((a,b)=>a.start_hour-b.start_hour||a.slot-b.slot);
const targetNameFor=r=>data.metadata?.targeting_profile_names?.[r.target||'none']||((r.target||'none')==='none'?'Untargeted':r.target);
const missionKey=r=>`${r.slot}|${r.ship}|${num(r.start_hour).toFixed(5)}|${num(r.end_hour).toFixed(5)}`+((r.target&&r.target!=='none')?'|target:'+r.target:'');
const planIdentity=sched.map(missionKey).join(';');
const storageKey='reggference-done-v2-'+targetId+'-'+(function(){let h=2166136261;for(let i=0;i<planIdentity.length;i++){h^=planIdentity.charCodeAt(i);h=Math.imul(h,16777619)}return (h>>>0).toString(36)})();
let completed=new Set();
try{completed=new Set(JSON.parse(localStorage.getItem(storageKey)||'[]'))}catch(e){}
function saveProgress(){try{localStorage.setItem(storageKey,JSON.stringify([...completed]))}catch(e){}}
function toggleDone(key){if(completed.has(key))completed.delete(key);else completed.add(key);saveProgress();drawTimeline();renderSchedule();scrollToProgress()}
const sleeps=(data.sleep_windows||[]).map(r=>({a:num(r.start_hour),b:num(r.end_hour)}));
const plans=data.launch_plan.map(r=>({...r,slot:num(r.slot),launches:num(r.launches),event_bonus:String(r.event_bonus).toLowerCase()==='true'}));
const windows=data.event_windows.filter(r=>String(r.event_bonus).toLowerCase()==='true').map(r=>({a:num(r.start_hour),b:num(r.end_hour)}));
const horizon=Math.max(24,...data.event_windows.map(r=>num(r.end_hour)),...sched.map(r=>r.end_hour));
const slots=[...new Set(sched.map(r=>r.slot))].sort((a,b)=>a-b);
const names=[...new Set(sched.map(r=>r.ship))].sort();
const fuels=['curiousity','kindness','resilence','integrity'];
const fuelUse=Object.fromEntries(fuels.map(f=>[f,plans.reduce((a,r)=>a+num(r[f+'_T']),0)]));
const totalFuel=Object.values(fuelUse).reduce((a,b)=>a+b,0);
document.getElementById('horizon').textContent= `${fmt(horizon/24,2)} day horizon`;
const newlyCrafted=num(data.craft_plan.find(r=>r.material_id===targetId)?.crafts);
const alreadyOwned=num(data.material_balance.find(r=>r.material_id===targetId)?.starting_inventory);
document.getElementById('craftTotal').textContent=fmt(newlyCrafted+alreadyOwned,0);
document.getElementById('inventorySummary').textContent=`${fmt(newlyCrafted,0)} newly crafted + ${fmt(alreadyOwned,0)} already owned (expected-drop model)`;
document.getElementById('launchTotal').textContent=fmt(sched.length,0);
document.getElementById('boostTotal').textContent=`${sched.filter(r=>r.event_bonus).length} event-boosted launches`;
document.getElementById('fuelTotal').textContent='Consumed: '+fmt(totalFuel,3)+'T';
document.getElementById('allocatedFuelTotal').textContent=data.summary?.allocated_fuel_T==null?'Unavailable':fmt(data.summary.allocated_fuel_T,3)+'T';
document.getElementById('completionDay').textContent='Actual completion: day '+fmt((data.summary?.completion_hour??Math.max(0,...sched.map(r=>r.end_hour)))/24,3);
if(guarantees?.crafts && !guarantees.crafts.proven){document.getElementById('planStatus').textContent=`Best feasible new crafts: ${fmt(guarantees.crafts.value,0)}; bound: ${guarantees.crafts.bound??'unknown'}; gap: ${guarantees.crafts.gap==null?'unknown':fmt(guarantees.crafts.gap*100,2)+'%'}`}
const freeShips=new Set(data.metadata?.zero_fuel_ships||[]);
const freeLaunches=plans.filter(r=>freeShips.has(r.ship)).reduce((sum,r)=>sum+r.launches,0);
document.getElementById('zeroFuelNote').textContent=freeLaunches?`${freeLaunches} launches use explicit zero fuel in mission.csv. Fuel-first optimization can require more launches.`:'';
document.getElementById('slotTotal').textContent=slots.length;
document.getElementById('eventTotal').textContent=windows.length+' capacity event'+(windows.length===1?'':'s');
let filter='all',search='',slot='all';
const filtered=r=>(!search||(r.ship+' '+targetNameFor(r)).toLowerCase().includes(search))&&(filter==='all'||(filter==='boost')===r.event_bonus);
function renderShips(){
 const by=new Map();
 for(const r of plans.filter(filtered)){
  const key=JSON.stringify([r.ship,r.target||'none']);
  const x=by.get(key)||{name:r.ship,target:targetNameFor(r),n:0,boost:0,fuel:0};
  x.n+=r.launches;if(r.event_bonus)x.boost+=r.launches;x.fuel+=num(r.total_fuel_T);by.set(key,x);
 }
 const arr=[...by.values()].sort((a,b)=>b.n-a.n);
 document.getElementById('ships').innerHTML=arr.length?arr.map(x=>`<article class="shipcard"><div class="name">${esc(x.name)}</div><div>Target: ${esc(x.target)}</div><div class="num">${fmt(x.n,0)} <span style="font-size:12px;color:var(--muted);font-weight:normal">launches</span></div><div class="mini"><span>Fuel ${fmt(x.fuel,3)}T</span><span>${x.boost?`${x.boost} boosted`: 'No event bonus'}</span></div></article>`).join(''):'<div class="empty">No matching ships.</div>';
}
function gapLabel(kind){return ({idle:'Idle / waiting','event-wait':'Possible capacity-event wait',sleep:'Sleep','no-launch':'Explicit no-launch','no-launch+sleep':'Sleep + explicit no-launch','unclassified-blackout':'Sleep / no-launch (legacy plan)'})[kind]||kind}
function renderGap(g){
 const totals=Object.entries(g.totals).map(([kind,h])=>`<span class="gap-reason ${esc(kind)}">${esc(gapLabel(kind))}: ${fmt(h,2)} h</span>`).join('');
 const segments=g.segments.map(w=>`<li>${day(w.start_hour)} – ${day(w.end_hour)}: ${esc(gapLabel(w.kind))} (${fmt(w.end_hour-w.start_hour,2)} h)</li>`).join('');
 return `<details class="lane-gap gap-details"><summary title="Gap since the previous actual mission in this slot">Gap ${fmt(g.hours,1)} h<br><small>Inspect breakdown</small></summary><div class="gap-breakdown">${totals}<p>${day(g.start_hour)} – ${day(g.end_hour)}</p><ul>${segments}</ul><small>Event waiting is a possibility, not proof that waiting was necessary.</small></div></details>`;
}
function drawTimeline(){
 const lanes=document.getElementById('lanes');
 lanes.innerHTML=slots.filter(s=>slot==='all'||Number(slot)===s).map(s=>{
  const all=sched.filter(r=>r.slot===s);const items=all.filter(filtered);
  const done=all.filter(r=>completed.has(missionKey(r))).length;
  const cells=items.map(r=>{
   const gap=r.gap_before?renderGap(r.gap_before):'';
   const k=missionKey(r),checked=completed.has(k), t=`${r.ship}, Slot ${r.slot}. ${day(r.start_hour)} to ${day(r.end_hour)}. Target: ${targetNameFor(r)}${r.event_bonus?', double capacity':''}. Click to ${checked?'undo':'complete'}.`;
   return gap+`<button type="button" class="mission-cell ${r.event_bonus?'boost':''} ${checked?'done':''}" data-mission="${esc(k)}" aria-pressed="${checked}" title="${esc(t)}"><span class="mission-name">${esc(r.ship)}</span><span class="mission-target">Target: ${esc(targetNameFor(r))}</span><span class="mission-time">Launch: ${day(r.start_hour)}<br>Finish: ${day(r.end_hour)}</span><span class="mission-flag">${checked?'✓ Completed':r.event_bonus?'✦ 2× capacity':'○ Not done'}</span></button>`;
  }).join('');
  return `<section class="checklane"><div class="lane-header"><strong>Slot ${s}</strong><small>${done}/${all.length} done</small><div class="mission-progress"><div style="width:${all.length?100*done/all.length:0}%"></div></div></div><div class="mission-scroll">${cells||'<div class="empty">No matching missions.</div>'}</div></section>`
 }).join('');
 const doneCount=sched.filter(r=>completed.has(missionKey(r))).length;
 document.getElementById('doneCount').textContent=`${doneCount} / ${sched.length} done`;
}
// Scroll each lane horizontally to its earliest unfinished launch, with a previous
// completed card visible as context. Never move the whole page on initial load.
function scrollToProgress(){
 const lanes=document.querySelectorAll('.mission-scroll');
 for(const lane of lanes){
  const cards=[...lane.querySelectorAll('.mission-cell')];
  if(!cards.length)continue;
  const next=cards.find(c=>c.getAttribute('aria-pressed')==='false');
  for(const c of cards)c.classList.toggle('next-up',c===next);
  const target=next||cards[cards.length-1];
  const prior=cards[Math.max(0,cards.indexOf(target)-1)];
  lane.scrollLeft=Math.max(0,prior.offsetLeft-lane.offsetLeft-12);
 }
}
function renderSchedule(){
 const rows=sched.filter(r=>(slot==='all'||r.slot===Number(slot))&&filtered(r));
 document.getElementById('scheduleRows').innerHTML=rows.length?rows.map(r=>{const k=missionKey(r),checked=completed.has(k);return `<tr><td>${day(r.start_hour)}</td><td>${day(r.end_hour)}</td><td>${r.slot}</td><td>${esc(r.ship)}</td><td>${esc(targetNameFor(r))}</td><td class="${r.event_bonus?'warn':''}">${r.event_bonus?'2× capacity':'Normal'}</td><td><button type="button" data-mission="${esc(k)}" class="${checked?'table-done':'table-undone'}" aria-pressed="${checked}">${checked?'✓ Done':'Mark done'}</button></td></tr>`}).join(''):'<tr><td colspan="7" class="empty">No matching launches.</td></tr>';
}
function renderFuel(){let max=Math.max(.001,...Object.values(fuelUse));document.getElementById('fuelPanel').innerHTML=fuels.map(f=>`<div class="fuelrow"><span>${f}</span><strong>${fmt(fuelUse[f],3)}T</strong></div><div class="progress"><div style="width:${100*fuelUse[f]/max}%"></div></div>`).join('')+`<div class="fuelrow"><span>Combined</span><strong>${fmt(totalFuel,3)}T</strong></div>`}
function renderCrafts(){document.getElementById('craftPanel').innerHTML=data.craft_plan.length?data.craft_plan.map(r=>`<div class="fuelrow"><span>${esc(r.material_id)}</span><strong class="${r.material_id===targetId?'good':''}">${fmt(r.crafts,0)}</strong></div>`).join(''):'<div class="empty">No crafts planned.</div>'}
function renderMaterials(){const q=document.getElementById('materialSearch').value.toLowerCase().trim();let rows=data.material_balance.filter(r=>r.material_id.toLowerCase().includes(q));document.getElementById('materials').innerHTML=rows.map(r=>`<tr><td>${esc(r.material_id)}</td><td class="numeric">${fmt(num(r.starting_inventory),0)}</td><td class="numeric">${fmt(r.expected_drops,3)}</td><td class="numeric">${fmt(r.crafted,0)}</td><td class="numeric">${fmt(r.consumed,3)}</td><td class="numeric ${num(r.expected_remaining)<1?'warn':''}">${fmt(r.expected_remaining,3)}</td></tr>`).join('')||'<tr><td colspan="6" class="empty">No matching materials.</td></tr>'}
function update(){renderShips();drawTimeline();renderSchedule();scrollToProgress()}
document.getElementById('search').addEventListener('input',e=>{search=e.target.value.trim().toLowerCase();update()});document.getElementById('boostFilter').addEventListener('change',e=>{filter=e.target.value;update()});const select=document.getElementById('slotFilter');for(let s of slots){let o=document.createElement('option');o.value=s;o.textContent='Slot '+s;select.appendChild(o)}select.addEventListener('change',e=>{slot=e.target.value;update()});document.addEventListener('click',e=>{const btn=e.target.closest('[data-mission]');if(btn)toggleDone(btn.dataset.mission)});
document.getElementById('jumpProgress').addEventListener('click',()=>{scrollToProgress();document.getElementById('lanes').scrollIntoView({behavior:'smooth',block:'start'})});
document.getElementById('exportProgress').addEventListener('click',()=>{const contents=JSON.stringify({format:'reggference-progress-v1',plan:storageKey,completed:[...completed]},null,2);const blob=new Blob([contents],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='reggference-progress.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)});
document.getElementById('importProgress').addEventListener('click',()=>document.getElementById('progressFile').click());
document.getElementById('progressFile').addEventListener('change',async e=>{const f=e.target.files?.[0];if(!f)return;try{const obj=JSON.parse(await f.text());if(obj.format!=='reggference-progress-v1'||obj.plan!==storageKey||!Array.isArray(obj.completed))throw Error('Progress file belongs to a different launch plan or has an invalid format');const keys=new Set(sched.map(missionKey));completed=new Set(obj.completed.filter(k=>keys.has(k)));saveProgress();drawTimeline();renderSchedule();scrollToProgress();alert('Progress imported.')}catch(err){alert('Could not import: '+err.message)}e.target.value=''});document.getElementById('materialSearch').addEventListener('input',renderMaterials);renderFuel();renderCrafts();renderMaterials();update();scrollToProgress();
</script></body></html>'''

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',default='results',help='Folder containing optimizer CSV outputs')
    parser.add_argument('--output',default=None,help='Path of resulting HTML (default: results/plan.html)')
    args=parser.parse_args()
    results=Path(args.results)
    build(results, Path(args.output) if args.output else results/'plan.html')
