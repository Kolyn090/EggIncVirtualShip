const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {createHash} = require('node:crypto');
let parsePlan, progressIdentity, validatePlan, renderDashboard, directory;

test.before(async () => {
  ({parsePlan, progressIdentity, validatePlan} = await import('../pwa/plan.mjs'));
  ({renderDashboard} = await import('../pwa/frame.mjs'));
  directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pwa-parser-'));
  execFileSync('python3', ['tests/pwa/fixtures.py', directory], {cwd: path.resolve(__dirname, '..')});
});
test.after(() => fs.rmSync(directory, {recursive: true, force: true}));

test('extracts actual generated data without altering schedules or invoking imported markup', () => {
  const html = fs.readFileSync(path.join(directory, 'first.html'), 'utf8');
  const original = JSON.parse(html.split('const data=')[1].split(';\ndocument.getElementById')[0]);
  const data = parsePlan(html.replace('</head>', '<img src="https://example.invalid/never"><script>throw Error("never executed")</script></head>'));
  assert.deepEqual(data, original);
  assert.equal(data.schedule.length, 3);
  assert.equal(data.metadata.target, 'ankh-4');
});

test('JSON braces and escaped strings cannot terminate data extraction', () => {
  const data = parsePlan(fs.readFileSync(path.join(directory, 'first.html'), 'utf8'));
  data.note = 'braces } ] { and quote " and slash \\ and </script> text';
  const embedded = JSON.stringify(data).replaceAll('</', '<\\/');
  assert.deepEqual(parsePlan('<script>const data = ' + embedded + '; throw Error("never")</script>'), data);
});

test('rejects missing, malformed, ambiguous and invalid mission data', () => {
  for (const html of ['<h1>no plan</h1>', '<script>const data={</script>', '<script>const data={}</script>']) {
    assert.throws(() => parsePlan(html));
  }
  const data = parsePlan(fs.readFileSync(path.join(directory, 'first.html'), 'utf8'));
  const html = '<script>const data=' + JSON.stringify(data) + ';</script>';
  assert.throws(() => parsePlan(html + html), /more than one plan/);
  for (const patch of [{slot: 0}, {slot: 1.5}, {start_hour: -1}, {end_hour: 'nan'}, {event_bonus: 'maybe'}]) {
    const bad = structuredClone(data); Object.assign(bad.schedule[0], patch);
    assert.throws(() => validatePlan(bad), /invalid mission/);
  }
  data.schedule.push({...data.schedule[0]});
  assert.throws(() => validatePlan(data), /duplicate/);
});

test('current and legacy untargeted keys preserve explicit backup compatibility', () => {
  const data = parsePlan(fs.readFileSync(path.join(directory, 'first.html'), 'utf8'));
  const a = progressIdentity(data);
  assert.match(a.storageKey, /^reggference-done-v2-ankh-4-/);
  assert.equal(a.keys[0], '1|henerprise-1|8.00000|17.60000|target:ankh');
  const row = data.schedule.find(row => row.target === 'none');
  const before = a.keys.find(key => key.includes('48.00000'));
  delete row.target;
  assert.equal(progressIdentity(data).keys.find(key => key.includes('48.00000')), before);
});

test('trusted rendering escapes script delimiters and never embeds original HTML', () => {
  const data = parsePlan(fs.readFileSync(path.join(directory, 'first.html'), 'utf8'));
  data.metadata.example = '</script><script>throw Error("injected")</script>';
  const identity = progressIdentity(data);
  const html = renderDashboard({id: 'one', data, progress: [], ...identity}, 'token');
  assert(!html.includes('</script><script>throw Error("injected")'));
  assert(html.includes("connect-src 'none'"));
  assert(html.includes('window.__planBridge'));
});

test('actual optimizer ship/target identifiers map to inspected highest-tier artwork', async () => {
  const {missionIcon} = await import('../pwa/icons.mjs');
  const {iconCatalog} = await import('../pwa/egginc-icons.mjs');
  const expectations = fs.readFileSync(path.resolve(__dirname, '../data/ship_material_expectations.csv'), 'utf8').trim().split('\n').slice(1).map(line => line.split(','));
  const ships = new Set(expectations.map(row => row[0])), targets = new Set(expectations.map(row => row[1]));
  for (const ship of ships) assert.equal(!!missionIcon('ship', ship), !ship.startsWith('henliner-'), ship);
  assert.equal(missionIcon('ship', 'chicken-one-0').file, 'afx_ship_chicken_1.png');
  assert.equal(missionIcon('ship', 'cornish-2').file, 'afx_ship_corellihen_corvette.png');
  assert.equal(missionIcon('ship', 'quintillion-chicken-3').file, 'afx_ship_millenium_chicken.png');
  for (const target of targets) {
    const icon = missionIcon('target', target);
    if (target === 'none') { assert.equal(icon, null); continue; }
    assert(icon, target);
    const rank = ['geode', 'meteorite', 'titanium'].includes(target) ? 3 : 4;
    assert.equal(icon.rank, rank, target);
    for (const tier of [1, 2, 3, 4]) assert.equal(missionIcon('target', target + '-' + tier).file, icon.file);
  }
  assert.equal(missionIcon('target', 'tungsten-ankh-1').file, 'afx_tungsten_ankh_4.png');
  assert.equal(missionIcon('target', 'titanium-ore-3').file, 'afx_solar_titanium_3.png');
  assert.equal(missionIcon('target', 'clarity-stone-fragment').file, 'afx_clarity_stone_4.png');
  assert.equal(Object.keys(iconCatalog.ships).length, 10);
  for (const value of ['unknown', '', 'https://example.invalid/image.png', '__proto__', null]) {
    assert.equal(missionIcon('target', value), null);
    assert.equal(missionIcon('ship', value), null);
  }
});

test('bundled PNGs match source checksums and embedded offline image bytes exactly', async () => {
  const {iconCatalog, iconImages} = await import('../pwa/egginc-icons.mjs');
  const manifest = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../pwa/assets/egginc/manifest.json'), 'utf8'));
  assert.deepEqual(iconCatalog, manifest);
  assert.equal(manifest.source.commit, '075805d987ae55d74579abff3f75f9b28e84d5fc');
  for (const [filename, checksum] of Object.entries(manifest.files)) {
    const bytes = fs.readFileSync(path.resolve(__dirname, '../pwa/assets/egginc', filename));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), checksum, filename);
    assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    assert.deepEqual(Buffer.from(iconImages[filename].split(',')[1], 'base64'), bytes);
  }
  for (const icon of [...Object.values(manifest.ships), ...Object.values(manifest.targets)]) assert(iconImages[icon.file]);
});

test('icon selection leaves plan data/identities intact and every bundled file is precached', async () => {
  const {planIcons} = await import('../pwa/icons.mjs');
  const data = parsePlan(fs.readFileSync(path.join(directory, 'first.html'), 'utf8'));
  const original = structuredClone(data), identity = progressIdentity(data);
  const icons = planIcons(data);
  assert.equal(icons.targets.ankh.file, 'afx_tungsten_ankh_4.png');
  assert.equal(icons.targets.none, null);
  assert.equal(Object.keys(icons.images).length, 3);
  assert.deepEqual(data, original); assert.deepEqual(progressIdentity(data), identity);
  const source = fs.readFileSync(path.resolve(__dirname, '../pwa/sw.js'), 'utf8');
  const cached = new Set(JSON.parse(source.match(/const ASSETS = (\[[\s\S]*?\]);/)[1]));
  for (const filename of ['icons.mjs', 'egginc-icons.mjs', 'assets/egginc/ATTRIBUTION.md',
    ...fs.readdirSync(path.resolve(__dirname, '../pwa/assets/egginc')).map(name => 'assets/egginc/' + name)]) {
    assert(cached.has('./' + filename), filename);
  }
});
