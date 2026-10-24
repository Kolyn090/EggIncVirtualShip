const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
let esbuild;
try{for(const dependency of ['esbuild','protobufjs','dayjs'])require.resolve(dependency);esbuild=require('esbuild')}
catch(error){throw Error('Missing Node dependencies. Run npm ci from the project root. '+error.message)}
const ROOT = path.resolve(__dirname, '../..');
const SHA = '8a9e04d299dba00af4b34ddf46241665fee30044';
const UPSTREAM = path.join(ROOT, '.cache/wasmegg-upstream');

function prepare() {
  if (!fs.existsSync(path.join(UPSTREAM,'.git'))) {
    fs.mkdirSync(path.dirname(UPSTREAM), {recursive:true});
    execFileSync('git',['clone','--filter=blob:none','--no-checkout','--depth','1','https://github.com/carpetsage/Egg.git',UPSTREAM],{stdio:'inherit'});
    execFileSync('git',['-C',UPSTREAM,'sparse-checkout','set','lib','protobuf','wasmegg/_common/eiafx'],{stdio:'inherit'});
    execFileSync('git',['-C',UPSTREAM,'fetch','--depth','1','origin',SHA],{stdio:'inherit'});
    execFileSync('git',['-C',UPSTREAM,'checkout','--detach',SHA],{stdio:'inherit'});
  }
  const actual=execFileSync('git',['-C',UPSTREAM,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
  if(actual!==SHA) throw Error(`Shared lib must be pinned to ${SHA}; found ${actual}. Remove .cache/wasmegg-upstream and retry.`);
  try{execFileSync('git',['-C',UPSTREAM,'diff','--quiet','HEAD','--','lib','protobuf','wasmegg/_common/eiafx'])}
  catch{throw Error('Pinned shared library has local changes; refusing unverified calculations')}
  return UPSTREAM;
}

async function loadRuntime() {
  prepare();
  const lib = path.join(UPSTREAM,'lib');
  const local = path.join(ROOT,'wasmegg/src');
  const entry = `export * from ${JSON.stringify(path.join(local,'lib/phases.ts'))};
    export * from ${JSON.stringify(path.join(lib,'missions.ts'))};
    export * from ${JSON.stringify(path.join(lib,'artifacts/data.ts'))};
    export * from ${JSON.stringify(path.join(local,'lib/loot.ts'))};
    export {ei} from 'proto-runtime';`;
  const bridge = `export * from ${JSON.stringify(path.join(lib,'missions.ts'))};
    export * from ${JSON.stringify(path.join(lib,'artifacts/data.ts'))}; export {ei} from 'proto-runtime';
    export function itemExpectedFullConsumption(){throw Error('Consumption values are outside this generator');}`;
  const virtual = {
    'bridge':bridge,
    'filter':`export {missions} from ${JSON.stringify(path.join(local,'lib/missions.ts'))};`,
    'presentation':`export function eggName(){throw Error('Presentation-only eggName is not supported');}
      export function eggIconPath(){throw Error('Presentation-only eggIconPath is not supported');}`,
    'proto-runtime':`const protobuf=require('protobufjs');const root=protobuf.loadSync(${JSON.stringify(path.join(UPSTREAM,'protobuf/ei.proto'))});
      function enums(n){if(n.values){const x={...n.values};for(const [k,v] of Object.entries(n.values))x[v]=k;return x}
      return Object.fromEntries(Object.entries(n.nested||{}).map(([k,v])=>[k,enums(v)]))}
      export const ei=enums(root).ei;`,
    'loot-runtime':`import fs from 'node:fs';export default JSON.parse(fs.readFileSync(${JSON.stringify(path.join(ROOT,'wasmegg/data/loot.json'))},'utf8'));`
  };
  const output=path.join(ROOT,'.cache/wasmegg-runtime.cjs');
  await esbuild.build({stdin:{contents:entry,resolveDir:ROOT,loader:'ts'},outfile:output,bundle:true,platform:'node',format:'cjs',
    nodePaths:[path.join(ROOT,'node_modules')],plugins:[{name:'headless-wasmegg',setup(build){
      build.onResolve({filter:/.*/},args=>{
        if(args.path==='lib')return {path:'bridge',namespace:'virtual'};
        if(args.path==='proto-runtime')return {path:'proto-runtime',namespace:'virtual'};
        if(args.path==='@/lib/filter')return {path:'filter',namespace:'virtual'};
        if(args.path==='@/lib')return {path:path.join(local,'lib/loot.ts')};
        if(args.path.startsWith('@/'))return {path:path.join(local,args.path.slice(2))+'.ts'};
        if(args.importer.startsWith(lib) && /^(\.\.\/|\.\/)proto$/.test(args.path))return {path:'proto-runtime',namespace:'virtual'};
        if(args.importer===path.join(lib,'missions.ts') && args.path==='./eggs')return {path:'presentation',namespace:'virtual'};
        if(args.importer===path.join(lib,'missions.ts') && args.path==='./artifacts')return {path:path.join(lib,'artifacts/data.ts')};
        if(args.importer===path.join(local,'lib/loot.ts') && args.path==='./loot-json')return {path:'loot-runtime',namespace:'virtual'};
      });
      build.onLoad({filter:/.*/,namespace:'virtual'},args=>({contents:virtual[args.path],loader:'ts',resolveDir:ROOT}));
    }}]});
  delete require.cache[output];
  return require(output);
}
module.exports={loadRuntime,prepare,SHA,ROOT,UPSTREAM};
