const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {generate,materialSource,validateRows}=require('../scripts/generate_ship_expectations');
const ROOT=path.resolve(__dirname,'..');
let data;
test.before(async()=>{data=await generate()});
test('untargeted expectation equals original wasmegg supply and independent histogram mean',()=>{
 const row=data.rows.find(r=>r.ship==='henerprise-1'&&r.target==='none'&&r.material_id==='ankh-3');
 const r=data.runtime,loot=r.getMissionLootData('henerprise-short').levels.find(l=>l.level===8).targets.find(t=>t.targetAfxId===r.ei.ArtifactSpec.Name.UNKNOWN);
 const item=loot.items.find(i=>i.itemId==='tungsten-ankh-3');
 assert.equal(row.expectation_per_launch,item.counts.reduce((a,b)=>a+b,0)/loot.totalDrops*127);
 assert(row.expectation_per_launch>1,'Expected units per mission is not a probability');
});
test('targeting redistributes families instead of applying one multiplier',()=>{
 const value=(target,material)=>data.rows.find(r=>r.ship==='henerprise-1'&&r.target===target&&r.material_id===material).expectation_per_launch;
 assert(value('ankh','ankh-3')>value('none','ankh-3'));
 assert(value('ankh','metronome-3')<value('none','metronome-3'));
});
test('all values finite/nonnegative or explicitly unknown, and unknowns stay blank',()=>{
 validateRows(data.rows);
 assert(data.rows.some(r=>r.status==='unobserved'&&r.expectation_per_launch===''));
 assert(data.rows.some(r=>r.status==='unknown_profile'&&r.expectation_per_launch===''));
 assert(data.rows.some(r=>r.status==='confirmed_zero'&&r.expectation_per_launch===0));
});
test('correct canonical tiers and explicit legacy titanium aliases',()=>{
 assert.equal(materialSource('metronome-3'),'quantum-metronome-3');
 assert.equal(materialSource('titanium-bar-3'),'solar-titanium-2');
 assert.equal(data.metadata.material_mapping['titanium-bar-3'].tier,2);
 assert.equal(data.metadata.material_mapping['titanium-ore-3'].tier,1);
 assert(data.metadata.recipe_warnings.some(w=>w.result==='ankh-3'));
});
test('only real FTL targets and no tutorial options',()=>{
 for(const p of data.metadata.profiles){const m=data.metadata.mission_parameters[p.ship];if(!m.is_ftl)assert.equal(p.target,'none');assert(data.runtime.targets.includes(p.target_id))}
 assert(!data.rows.some(r=>r.ship==='chicken-one-0'));
 assert(!data.rows.some(r=>r.ship==='bcr-1'&&r.target==='ankh'));
 assert(data.metadata.excluded_missions.some(m=>m.ship==='chicken-one-0'));
});
test('empirical profile probabilities sum to capacity across all items',()=>{
 const r=data.runtime,m=r.getMissionTypeFromId('henerprise-short');
 const options=r.enumerateLaunchOptions({...r.perfectShipsConfig,showNodata:true},new Map(r.allPossibleTiers.map(t=>[t.id,{}])));
 const option=options.find(o=>o.id==='henerprise-short::12');
 assert(Math.abs([...option.supplyVector.values()].reduce((a,b)=>a+b,0)-m.boostedCapacity(r.perfectShipsConfig))<1e-9);
});
test('generation is deterministic and matches published bytes',async()=>{
 const second=await generate();assert.equal(data.csv,second.csv);assert.deepEqual(data.metadata,second.metadata);
 const candidate=path.join(ROOT,'data/ship_material_expectations.csv');if(fs.existsSync(candidate))assert.equal(data.csv,fs.readFileSync(candidate,'utf8'));
});
test('missing required inputs fail clearly without a legacy fallback',async()=>{
 await assert.rejects(generate({recipeDir:path.join(ROOT,'data/does-not-exist')}));
});
