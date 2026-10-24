#!/usr/bin/env node
/* Empirical expectations via the original wasmegg enumerateLaunchOptions function. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {loadRuntime,SHA,ROOT}=require('./wasmegg/runtime');
const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
const aliases={metronome:'quantum-metronome',ankh:'tungsten-ankh',geode:'tau-ceti-geode',meteorite:'gold-meteorite',lens:'mercurys-lens',actuator:'titanium-actuator'};
const special={'titanium-bar-3':'solar-titanium-2','titanium-ore-3':'solar-titanium-1'};
const shipAliases={'atreggies':'henliner','millenium-chicken':'quintillion-chicken','corellihen-corvette':'cornish','chickfiant':'defihent','chicken-heavy':'heavy'};
const csvCell=x=>String(x??'').includes(',')||String(x??'').includes('"')||String(x??'').includes('\n')?'"'+String(x).replaceAll('"','""')+'"':String(x??'');
function parseCsv(text){
  const lines=text.replace(/^\uFEFF/,'').trim().split(/\r?\n/);const keys=lines.shift().split(',');
  return lines.map(line=>Object.fromEntries(line.split(',').map((v,i)=>[keys[i],v])));
}
function materialSource(id){if(special[id])return special[id];const match=id.match(/^(.*)-(\d+)$/);return match&&aliases[match[1]]?`${aliases[match[1]]}-${match[2]}`:id}
function targetSlug(r,id){if(id===r.ei.ArtifactSpec.Name.UNKNOWN)return 'none';const canonical=r.getArtifactFamilyProps(id)?.id||r.ei.ArtifactSpec.Name[id].toLowerCase().replaceAll('_','-');return Object.keys(aliases).find(k=>aliases[k]===canonical)|| (canonical==='solar-titanium'?'titanium':canonical)}
function shipId(m){return `${shipAliases[m.missionTypeId.replace(/-(short|standard|extended)$/,'')]||m.missionTypeId.replace(/-(short|standard|extended)$/,'')}-${m.durationType+1}`}
function requiredMaterials(directory){
 const files=fs.readdirSync(directory).filter(f=>f.endsWith('.csv')).sort();if(!files.length)throw Error('No recipe CSV files in '+directory);
 const materials=new Set();for(const file of files)for(const row of parseCsv(fs.readFileSync(path.join(directory,file),'utf8'))){if(!row.result||!row.ingredient)throw Error('Malformed recipe '+file);materials.add(row.result);materials.add(row.ingredient)}
 return [...materials].sort();
}
function validateRows(rows){
 const seen=new Set();for(const row of rows){const key=[row.ship,row.target,row.material_id].join('|');if(seen.has(key))throw Error('Duplicate expectation '+key);seen.add(key);
  if(row.expectation_per_launch!=='' && (!Number.isFinite(row.expectation_per_launch)||row.expectation_per_launch<0))throw Error('Invalid expectation '+key);
  if(!row.material_id||!row.target||!row.ship)throw Error('Missing identifiers');
 }
}
async function generate({configPath=path.join(ROOT,'data/ship_expectations_config.json'),recipeDir=path.join(ROOT,'data/artifact-recipes')}={}){
 const r=await loadRuntime(),user=JSON.parse(fs.readFileSync(configPath,'utf8'));
 for(const [key,max] of [['epicResearchFTLLevel',60],['epicResearchZerogLevel',10]])if(!Number.isInteger(user[key])||user[key]<0||user[key]>max)throw Error('Invalid research level '+key);
 if(!Number.isFinite(user.minimumEquivalentMissions)||user.minimumEquivalentMissions<0)throw Error('Invalid minimumEquivalentMissions');
 const config={...r.perfectShipsConfig,...user,shipLevels:{...r.perfectShipsConfig.shipLevels},shipVisibility:{...r.perfectShipsConfig.shipVisibility},showNodata:true};
 for(const [name,level] of Object.entries(user.shipLevels||{})){
  const m=r.allMissionTypes.find(m=>shipId(m).replace(/-\d+$/,'')===name&&m.durationType!==r.ei.MissionInfo.DurationType.TUTORIAL);
  if(!m||!Number.isInteger(level)||level<0||level>m.maxLevel)throw Error('Invalid ship level '+name);
  config.shipLevels[m.shipType]=level;
 }
 const materials=requiredMaterials(recipeDir),mapping={};
 for(const id of materials){const source=materialSource(id),props=r.getArtifactTierPropsFromId(source);mapping[id]={source_material_id:source,afx_id:props.afx_id,afx_level:props.afx_level,tier:props.tier_number,name:props.name};}
 for(const mission of r.allMissionTypes.filter(m=>m.durationType!==r.ei.MissionInfo.DurationType.TUTORIAL)){
  const level=config.shipLevels[mission.shipType];if(r.getMissionLootData(mission.missionTypeId).levels[level]?.level!==level)throw Error(`Missing or unordered loot star bucket ${mission.missionTypeId}/${level}`);
 }
 const dag=new Map(r.allPossibleTiers.map(t=>[t.id,{}]));
 const options=r.enumerateLaunchOptions(config,dag),optionMap=new Map(options.map(o=>[o.id,o]));
 const csvMissions=new Set(parseCsv(fs.readFileSync(path.join(ROOT,'data/mission.csv'),'utf8')).map(m=>m.ship));
 const metadata={schema_version:2,source:'wasmegg empirical loot counts',shared_lib_commit:SHA,assumptions:user,material_mapping:mapping,mission_parameters:{},profiles:[],excluded_missions:[],source_hashes:{},recipe_warnings:[]};
 for(const f of ['wasmegg/data/loot.json','wasmegg/src/lib/phases.ts','wasmegg/src/lib/loot.ts','wasmegg/src/lib/missions.ts'])metadata.source_hashes[f]=hash(fs.readFileSync(path.join(ROOT,f)));
 // Surface supplied recipe differences rather than silently changing inventory or recipes.
 for(const file of fs.readdirSync(recipeDir).filter(f=>f.endsWith('.csv')).sort()){
  const recipes=parseCsv(fs.readFileSync(path.join(recipeDir,file),'utf8'));
  for(const result of new Set(recipes.map(x=>x.result))){const props=r.getArtifactTierPropsFromId(materialSource(result));
   const actual=(props.recipe?.ingredients||[]).map(x=>`${x.id}:${x.count}`).sort();
   const supplied=recipes.filter(x=>x.result===result).map(x=>`${materialSource(x.ingredient)}:${Number(x.quantity)}`).sort();
   if(JSON.stringify(actual)!==JSON.stringify(supplied))metadata.recipe_warnings.push({file,result,upstream:actual,supplied});
  }
 }
 const rows=[];
 for(const mission of r.allMissionTypes){
  if(mission.durationType===r.ei.MissionInfo.DurationType.TUTORIAL)continue;
  const ship=shipId(mission);if(!csvMissions.has(ship))throw Error('No optimizer mission mapping for '+mission.missionTypeId);
  const level=config.shipLevels[mission.shipType],loot=r.getMissionLootData(mission.missionTypeId),levelLoot=loot.levels.find(l=>l.level===level);
  const capacity=mission.boostedCapacity(config),duration=mission.boostedDurationSeconds(config)/3600;
  if(!Number.isFinite(capacity)||capacity<=0||!Number.isFinite(duration)||duration<=0)throw Error('Invalid mission attributes '+ship);
  metadata.mission_parameters[ship]={source_mission_id:mission.missionTypeId,stars:level,capacity,duration_hours:duration,min_quality:mission.params.minQuality,max_quality:mission.boostedMaxQuality(config),is_ftl:mission.isFTL};
  for(const targetId of mission.isFTL?r.targets:[r.ei.ArtifactSpec.Name.UNKNOWN]){
   const target=targetSlug(r,targetId),profile=levelLoot?.targets.find(x=>x.targetAfxId===targetId),option=optionMap.get(`${mission.missionTypeId}::${targetId}`);
   const total=profile?.totalDrops||0;
   const usable=!!option&&total>0&&total/mission.maxBoostedCapacity()>=user.minimumEquivalentMissions;
   metadata.profiles.push({ship,target,target_id:targetId,target_name:target==='none'?'Untargeted':r.getTargetName(targetId),total_drops:total,usable,
     reason:usable?'empirical':total===0?'no_observations':'insufficient_observations'});
   if(profile){for(const item of profile.items){
    if(item.counts.length!==4||item.counts.some(n=>!Number.isSafeInteger(n)||n<0))throw Error('Invalid rarity counts for '+item.itemId);
    const props=r.getArtifactTierPropsFromId(item.itemId);if(props.afx_id!==item.afxId||props.afx_level!==item.afxLevel)throw Error('Artifact ID/tier mismatch for '+item.itemId);
   }const counted=profile.items.reduce((n,i)=>n+i.counts.reduce((a,b)=>a+b,0),0);if(counted!==total)throw Error(`Loot counts do not sum to denominator for ${ship}/${target}: ${counted} != ${total}`)}
   for(const material of materials){const props=r.getArtifactTierPropsFromId(mapping[material].source_material_id),item=profile?.items.find(x=>x.itemId===props.id);
    const count=item?item.counts.reduce((a,b)=>a+b,0):0;
    let value='',status=usable?'unobserved':'unknown_profile';
    if(!props.available_from_missions||props.quality<mission.params.minQuality||props.quality>mission.boostedMaxQuality(config)){
     if(!count){value=0;status='confirmed_zero'}
    }
    if(usable&&count>0){value=option.supplyVector.get(props.id);status='empirical';if(value===undefined)throw Error('wasmegg did not return supply for '+props.id)}
    rows.push({ship,target,material_id:material,expectation_per_launch:value,status,observed_count:count,total_drops:total});
   }
  }
 }
 for(const ship of csvMissions)if(!metadata.mission_parameters[ship])metadata.excluded_missions.push({ship,reason:ship==='chicken-one-0'?'nonrepeatable tutorial mission':'missing mission definition'});
 validateRows(rows);rows.sort((a,b)=>a.ship.localeCompare(b.ship,'en')||a.target.localeCompare(b.target,'en')||a.material_id.localeCompare(b.material_id,'en'));
 const header=['ship','target','material_id','expectation_per_launch','status','observed_count','total_drops'];
 const csv=header.join(',')+'\n'+rows.map(row=>header.map(k=>csvCell(row[k])).join(',')).join('\n')+'\n';metadata.csv_sha256=hash(csv);
 return {csv,metadata,rows,runtime:r};
}
async function main(){
 const args=process.argv.slice(2);let output=path.join(ROOT,'data/ship_material_expectations.csv'),configPath,recipeDir;
 for(let i=0;i<args.length;i++){const arg=args[i],value=args[++i];if(!value)throw Error('Missing argument value for '+arg);if(arg==='--output')output=path.resolve(value);else if(arg==='--config')configPath=path.resolve(value);else if(arg==='--recipe-dir')recipeDir=path.resolve(value);else throw Error('Unknown argument '+arg)}
 const result=await generate({configPath,recipeDir});fs.mkdirSync(path.dirname(output),{recursive:true});
 // All validation has completed before replacing either file. Preserve the first pre-generation CSV.
 const backup=output.replace(/\.csv$/,'.legacy.csv');if(fs.existsSync(output)&&!fs.existsSync(backup))fs.copyFileSync(output,backup,fs.constants.COPYFILE_EXCL);
 const meta=output.replace(/\.csv$/,'.metadata.json');
 fs.writeFileSync(output+'.tmp',result.csv);fs.writeFileSync(meta+'.tmp',JSON.stringify(result.metadata,null,2)+'\n');
 fs.renameSync(meta+'.tmp',meta);fs.renameSync(output+'.tmp',output);
 console.log(`Generated ${result.rows.length} rows; ${result.metadata.profiles.filter(p=>p.usable).length} usable profiles. Empirical point estimates, not exact game probabilities.`);
 if(result.metadata.recipe_warnings.length)console.log('Recipe/source differences are recorded in '+meta);
}
if(require.main===module)main().catch(e=>{console.error('Expectation generation failed: '+e.message);process.exitCode=1});
module.exports={generate,materialSource,targetSlug,shipId,validateRows};
