const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
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
