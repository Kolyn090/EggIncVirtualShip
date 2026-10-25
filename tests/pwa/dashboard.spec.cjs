const {test, expect, chromium} = require('@playwright/test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
let fixtures;

test.beforeAll(() => {
  fixtures = fs.mkdtempSync(path.join(os.tmpdir(), 'mission-plan-browser-'));
  execFileSync('python3', ['tests/pwa/fixtures.py', fixtures], {cwd: path.resolve(__dirname, '../..')});
  const root = path.resolve(__dirname, '../..');
  const python = fs.existsSync(path.join(root, '.venv/bin/python')) ? path.join(root, '.venv/bin/python') : 'python3';
  execFileSync(python, ['tests/pwa/fuel_inventory_fixture.py', fixtures], {cwd: root});
});
test.afterAll(() => fs.rmSync(fixtures, {recursive: true, force: true}));

async function open(page) {
  await page.goto('./');
  await expect(page.getByRole('heading', {name: 'Import Plan', exact: true})).toBeVisible();
  await expect(page.locator('#offlineStatus')).toHaveText('Ready offline');
}
async function importFile(page, name = 'first') {
  await page.locator('#planFile').setInputFiles(path.join(fixtures, name + '.html'));
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await expect(page.locator('#planName')).toHaveText(name + '.html');
  const dashboard = page.frameLocator('#dashboard');
  await expect(dashboard.locator('.mission-cell')).toHaveCount(3);
  return dashboard;
}
async function closeCurrent(page) {
  await page.getByRole('button', {name: 'Close Current Plan', exact: true}).click();
  await expect(page.getByRole('dialog')).toContainText('delete the current plan and all its checklist progress');
  await page.getByRole('button', {name: 'Close and delete', exact: true}).click();
  await expect(page.getByRole('heading', {name: 'Import Plan', exact: true})).toBeVisible();
}

test('actual fixed-fuel optimizer plan imports, reports inventory and retains progress offline', async ({page, context}) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({width:390,height:844});
  await open(page);
  const dashboard = await importFile(page, 'fuel-inventory');
  await expect(dashboard.locator('#fuelMode')).toHaveText('Fuel: existing inventory (no replenishment)');
  await expect(dashboard.locator('#allocatedFuelTotal')).toHaveText('105.5T');
  await expect(dashboard.locator('#fuelTotal')).toHaveText('Consumed: 105T · Remaining: 500B');
  await expect(dashboard.locator('#fuelInventoryTable tbody tr')).toHaveCount(5);
  const fuelScroll = dashboard.locator('#fuelPanel .tablewrap');
  expect(await fuelScroll.evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true);
  await fuelScroll.evaluate(element => { element.scrollLeft = element.scrollWidth; });
  expect(await fuelScroll.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
  expect(await dashboard.locator('body').evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const curiosity = dashboard.locator('#fuelInventoryTable tbody tr').filter({hasText: 'Curiosity'});
  await expect(curiosity).toContainText('45.5T'); await expect(curiosity).toContainText('45T');
  await expect(curiosity).toContainText('500B');
  const first = dashboard.locator('.mission-cell').first();
  await expect(first.locator('.mission-name img')).toHaveAttribute('data-icon-file','afx_ship_henerprise.png');
  await expect(first.locator('.mission-target img')).toHaveAttribute('data-icon-file','afx_tungsten_ankh_4.png');
  await expect(first.locator('.mission-length-badge')).toHaveText('S');
  await first.click(); await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  const times = await page.evaluate(async () => (await (await import('./store.mjs')).readActivePlan()).completionTimes);
  const downloadPromise = page.waitForEvent('download');
  await dashboard.getByRole('button', {name:'Export progress',exact:true}).click();
  const backup = path.join(fixtures,'fixed-fuel-backup.json'); await (await downloadPromise).saveAs(backup);
  await context.setOffline(true); await page.reload();
  await expect(first).toHaveClass(/latest-completed/);
  await expect(first.locator('.completion-time')).toHaveText('Just now');
  await expect(dashboard.locator('#fuelInventoryTable')).toContainText('500B');
  expect(await page.evaluate(async () => (await (await import('./store.mjs')).readActivePlan()).completionTimes)).toEqual(times);
  await expect(page.locator('#planFile')).toBeDisabled();
  await first.click(); await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await dashboard.locator('#progressFile').setInputFiles(backup);
  await expect(first).toHaveClass(/latest-completed/);
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  expect(errors).toEqual([]);
});

test('local import, automatic check/uncheck saves, reload, and progress backup', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await open(page);
  const dashboard = await importFile(page);
  const first = dashboard.locator('.mission-cell').first();
  await first.click();
  await expect(first).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await page.reload();
  await expect(dashboard.locator('.mission-cell').first()).toHaveAttribute('aria-pressed', 'true');
  const downloadPromise = page.waitForEvent('download');
  await dashboard.getByRole('button', {name: 'Export progress', exact: true}).click();
  const download = await downloadPromise;
  const backup = path.join(fixtures, 'backup.json');
  await download.saveAs(backup);
  const contents = JSON.parse(fs.readFileSync(backup, 'utf8'));
  expect(contents.format).toBe('reggference-progress-v1');
  expect(contents.completed).toHaveLength(1);
  expect(contents.completionTimes[contents.completed[0]]).toBeGreaterThan(0);
  await dashboard.locator('.mission-cell').first().click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await page.reload();
  await expect(dashboard.locator('.mission-cell').first()).toHaveAttribute('aria-pressed', 'false');
  await dashboard.locator('#progressFile').setInputFiles(backup);
  await expect(dashboard.locator('.mission-cell').first()).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await page.reload();
  await expect(dashboard.locator('.mission-cell').first()).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(async () => (await (await import('./store.mjs')).readActivePlan()).completionTimes)).toEqual(contents.completionTimes);
  expect(errors).toEqual([]);
});

test('imports blocked while active; cancelled close preserves data; confirmed close deletes it', async ({page}) => {
  await open(page);
  const historyLength = await page.evaluate(() => history.length);
  let dashboard = await importFile(page);
  await dashboard.locator('.mission-cell').first().click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  const previous = await page.evaluate(async () => (await import('./store.mjs')).readActivePlan());
  await expect(page.locator('#importScreen')).toBeHidden();
  await expect(page.locator('#planFile')).toBeDisabled();
  await page.locator('#planFile').setInputFiles(path.join(fixtures, 'second.html'));
  await expect(page.locator('#planName')).toHaveText('first.html');
  expect(await page.evaluate(async () => {
    const store = await import('./store.mjs');
    try { await store.importPlan({}, 'replacement', {}); return false; } catch { return true; }
  })).toBe(true);
  await page.getByRole('button', {name: 'Close Current Plan', exact: true}).click();
  await page.getByRole('button', {name: 'Keep current plan', exact: true}).click();
  await page.reload();
  await expect(dashboard.locator('.mission-cell').first()).toHaveAttribute('aria-pressed', 'true');
  await closeCurrent(page);
  expect(await page.evaluate(async () => (await import('./store.mjs')).readActivePlan())).toBeNull();
  // Late writes from the closed frame cannot recreate a record.
  expect(await page.evaluate(async old => {
    try { await (await import('./store.mjs')).saveProgress(old.id, old.keys, []); return false; } catch { return true; }
  }, previous)).toBe(true);
  await page.reload();
  await expect(page.getByRole('heading', {name: 'Import Plan', exact: true})).toBeVisible();
  // Even an unrelated standalone dashboard's old localStorage key is ignored.
  await page.evaluate(old => localStorage.setItem(old.storageKey, JSON.stringify(old.progress)), previous);
  dashboard = await importFile(page);
  await expect(dashboard.locator('.mission-cell.done')).toHaveCount(0);
  await closeCurrent(page);
  await importFile(page, 'second');
  expect(await page.evaluate(() => history.length)).toBe(historyLength);
});

test('whole-browser restart restores the plan/checklist offline, then closes/imports offline', async ({baseURL}) => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'mission-plan-profile-'));
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
    (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined);
  let context;
  try {
    context = await chromium.launchPersistentContext(profile, {headless: true, executablePath});
    let page = context.pages()[0];
    await page.goto(baseURL);
    await expect(page.locator('#offlineStatus')).toHaveText('Ready offline');
    let dashboard = await importFile(page, 'henliner');
    await dashboard.locator('.mission-cell').first().click();
    await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
    const savedTimes = await page.evaluate(async () => (await (await import('./store.mjs')).readActivePlan()).completionTimes);
    await context.close();
    context = await chromium.launchPersistentContext(profile, {headless: true, executablePath, offline: true});
    page = context.pages()[0];
    await page.goto(baseURL);
    dashboard = page.frameLocator('#dashboard');
    await expect(dashboard.locator('.mission-cell.done')).toHaveCount(1);
    await expect(dashboard.locator('.mission-cell.latest-completed')).toHaveCount(1);
    await expect(dashboard.locator('.latest-completed .completion-time').first()).toHaveText('Just now');
    await expect(dashboard.locator('.mission-cell .mission-icon')).toHaveCount(5);
    await expect(dashboard.locator('.mission-cell .mission-name img[data-icon-file="afx_ship_atreggies.png"]')).toHaveCount(3);
    expect(await dashboard.locator('.mission-cell .mission-length-badge').allTextContents()).toEqual(['S', 'E', 'M']);
    await expect.poll(() => dashboard.locator('.mission-icon').evaluateAll(images => images.every(image => image.complete && image.naturalWidth > 0))).toBe(true);
    // Check raw bundled assets as well as embedded frame images with the entire
    // browser offline after restart (including repository-subpath deployment).
    expect(await page.evaluate(async () => {
      const {iconCatalog} = await import('./egginc-icons.mjs');
      const responses = await Promise.all(Object.keys(iconCatalog.files).map(name => fetch('./assets/egginc/' + name)));
      return responses.every(response => response.ok);
    })).toBe(true);
    expect(await page.evaluate(async () => (await (await import('./store.mjs')).readActivePlan()).completionTimes)).toEqual(savedTimes);
    await dashboard.locator('.mission-cell').first().click();
    await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
    await page.reload();
    await expect(dashboard.locator('.mission-cell.done')).toHaveCount(0);
    await closeCurrent(page);
    await page.reload();
    await expect(page.getByRole('heading', {name: 'Import Plan', exact: true})).toBeVisible();
    await importFile(page, 'second');
  } finally {
    await context?.close();
    fs.rmSync(profile, {recursive: true, force: true});
  }
});

test('latest completion changes, unchecking falls back, and relative times update without reload', async ({page}) => {
  await page.clock.install({time: new Date('2026-10-25T12:00:00Z')});
  await open(page);
  const dashboard = await importFile(page);
  const first = dashboard.locator('.mission-cell').nth(0), second = dashboard.locator('.mission-cell').nth(1);
  const firstKey = await first.getAttribute('data-mission');
  await first.click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await expect(first).toHaveClass(/latest-completed/);
  await expect(first.locator('.completion-time')).toHaveText('Just now');
  const firstTime = await page.evaluate(async key => (await (await import('./store.mjs')).readActivePlan()).completionTimes[key], firstKey);
  expect(firstTime).toBeGreaterThanOrEqual(Date.parse('2026-10-25T12:00:00Z'));
  await page.clock.fastForward('03:00');
  await expect(first.locator('.completion-time')).toHaveText('3 min ago');
  await second.click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await expect(second).toHaveClass(/latest-completed/);
  await expect(first).not.toHaveClass(/latest-completed/);
  expect(await first.evaluate(cell => getComputedStyle(cell).backgroundColor)).toBe('rgb(22, 70, 58)');
  expect(await second.evaluate(cell => getComputedStyle(cell).backgroundColor)).toBe('rgb(244, 214, 107)');
  await second.click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await expect(first).toHaveClass(/latest-completed/);
  const record = await page.evaluate(async () => (await import('./store.mjs')).readActivePlan());
  expect(record.completionTimes).toEqual({[firstKey]: firstTime});
  await page.reload();
  await expect(first).toHaveClass(/latest-completed/);
  await expect(first.locator('.completion-time')).toHaveText('3 min ago');
  await page.clock.fastForward(24 * 60 * 60 * 1000);
  await expect(first.locator('.completion-time')).toContainText('Yesterday,');
  await first.click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await expect(dashboard.locator('.mission-cell.latest-completed')).toHaveCount(0);
  await page.clock.fastForward('01:00');
  await first.click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  expect(await page.evaluate(async key => (await (await import('./store.mjs')).readActivePlan()).completionTimes[key], firstKey)).toBeGreaterThan(firstTime);
  await expect(first.locator('.completion-time')).toHaveText('Just now');
});

test('old saved records and old backups retain checks without inventing timestamps', async ({page}) => {
  await open(page);
  const dashboard = await importFile(page);
  const record = await page.evaluate(async () => {
    const store = await import('./store.mjs'), record = await store.readActivePlan();
    // Simulate the exact record shape written by the previous PWA release.
    await new Promise((resolve, reject) => {
      const request = indexedDB.open('egginc-active-mission-plan', 1);
      request.onsuccess = () => {
        const db = request.result, tx = db.transaction('state', 'readwrite');
        record.progress = record.keys.slice(0, 2); delete record.completionTimes;
        tx.objectStore('state').put(record, 'active');
        tx.oncomplete = () => { db.close(); resolve(); }; tx.onerror = () => reject(tx.error);
      };
    });
    return record;
  });
  await page.reload();
  await expect(dashboard.locator('.mission-cell.done')).toHaveCount(2);
  await expect(dashboard.locator('.mission-cell.latest-completed')).toHaveCount(1);
  await expect(dashboard.locator('.mission-cell.done .completion-time').first()).toHaveText('Completion time unavailable');
  // A real new completion outranks unknown legacy times and upgrades in place.
  const newKey = record.keys[2];
  await dashboard.locator('.mission-cell').filter({has: dashboard.locator('.mission-flag', {hasText: 'Not done'})}).click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  expect(await page.evaluate(async key => (await (await import('./store.mjs')).readActivePlan()).completionTimes[key], newKey)).toBeGreaterThan(0);
  // Legacy backup can restore unknown-time entries, while retaining known times
  // for checks already in the active record.
  const backup = {format: 'reggference-progress-v1', plan: record.storageKey, completed: record.keys};
  await dashboard.locator('#progressFile').setInputFiles({name: 'old.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(backup))});
  await expect(page.locator('#message')).toHaveText('Progress imported.');
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  const current = await page.evaluate(async () => (await import('./store.mjs')).readActivePlan());
  expect(current.progress).toHaveLength(3);
  expect(Object.keys(current.completionTimes)).toEqual([newKey]);
  await page.reload();
  await expect(dashboard.locator('.mission-cell.done')).toHaveCount(3);
  await expect(dashboard.locator('.mission-cell.latest-completed')).toHaveAttribute('data-mission', newKey);
  // Restoring previously unchecked entries from a legacy backup marks them
  // complete without assigning the time of the import as their completion.
  await dashboard.locator('.mission-cell.latest-completed').click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await dashboard.locator('#progressFile').setInputFiles({name: 'old-again.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(backup))});
  await expect(dashboard.locator('.mission-cell.done')).toHaveCount(3);
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  expect(await page.evaluate(async () => (await (await import('./store.mjs')).readActivePlan()).completionTimes)).toEqual({});
});

test('two windows racing imports share one record; stale close cannot delete the next plan', async ({page, context}) => {
  await open(page);
  const other = await context.newPage();
  await open(other);
  await Promise.all([page.locator('#planFile').setInputFiles(path.join(fixtures, 'first.html')),
    other.locator('#planFile').setInputFiles(path.join(fixtures, 'second.html'))]);
  await expect(page.locator('#activeToolbar')).toBeVisible();
  await expect(other.locator('#activeToolbar')).toBeVisible();
  await expect(other.locator('#planName')).toHaveText(await page.locator('#planName').textContent());
  const old = await page.evaluate(async () => (await import('./store.mjs')).readActivePlan());
  await closeCurrent(page);
  await expect(other.locator('#importScreen')).toBeVisible();
  await importFile(other, 'second');
  expect(await page.evaluate(async id => {
    try { await (await import('./store.mjs')).closePlan(id); return false; } catch { return true; }
  }, old.id)).toBe(true);
  await expect(other.locator('#planName')).toHaveText('second.html');
});

test('untrusted HTML content never executes or uploads; import errors keep storage empty', async ({page}) => {
  await open(page);
  const requests = [];
  page.on('request', request => { if (request.method() !== 'GET' || request.url().includes('/must-not-run')) requests.push(request.url()); });
  await page.locator('#planFile').setInputFiles({name: 'invalid.html', mimeType: 'text/html', buffer: Buffer.from('<script>fetch("/must-not-run")</script>')});
  await expect(page.locator('#message')).toContainText('optimizer-generated HTML');
  expect(await page.evaluate(async () => (await import('./store.mjs')).readActivePlan())).toBeNull();
  const html = fs.readFileSync(path.join(fixtures, 'first.html'), 'utf8').replace('</head>', '<img src="/must-not-run"><script>fetch("/must-not-run",{method:"POST"})</script></head>');
  await page.locator('#planFile').setInputFiles({name: 'plan.html', mimeType: 'text/html', buffer: Buffer.from(html)});
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await expect(page.frameLocator('#dashboard').locator('.mission-cell')).toHaveCount(3);
  expect(requests).toEqual([]);
});

test('mobile controls, mission cards, and failed saves remain usable', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await open(page);
  const dashboard = await importFile(page);
  await expect(page.getByRole('button', {name: 'Close Current Plan', exact: true})).toBeInViewport();
  await expect(dashboard.locator('.mission-cell').first()).toBeVisible();
  const bounds = await page.locator('#dashboard').boundingBox();
  expect(bounds.width).toBeLessThanOrEqual(390);
  // Force a real database transaction failure, rather than pretending it saved.
  await page.evaluate(() => { window.originalTransaction = IDBDatabase.prototype.transaction;
    IDBDatabase.prototype.transaction = function(...args) { if (args[1] === 'readwrite') throw Error('Test storage unavailable'); return window.originalTransaction.apply(this, args); }; });
  await dashboard.locator('.mission-cell').first().click();
  await expect(page.locator('#saveStatus')).toHaveText('Checklist could not be saved');
  await expect(page.locator('#retrySave')).toBeVisible();
  const actionTimes = await dashboard.locator('body').evaluate(() => window.__planBridge.completionTimes);
  await page.evaluate(() => { IDBDatabase.prototype.transaction = window.originalTransaction; });
  await page.locator('#retrySave').click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await page.reload();
  await expect(dashboard.locator('.mission-cell.done')).toHaveCount(1);
  expect(await page.evaluate(async () => (await (await import('./store.mjs')).readActivePlan()).completionTimes)).toEqual(actionTimes);
});

test('compact icon checklist keeps mission details, touch targets and desktop card dimensions', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await open(page);
  const dashboard = await importFile(page);
  async function dimensions() {
    return dashboard.locator('.checklane').first().evaluate(lane => {
      return {height: lane.getBoundingClientRect().height,
        width: lane.querySelector('.mission-cell').getBoundingClientRect().width,
        cardHeight: lane.querySelector('.mission-cell').getBoundingClientRect().height};
    });
  }
  const mobile = await dimensions();
  console.log('Mobile checklist dimensions:', JSON.stringify(mobile));
  expect(mobile.width).toBe(128);
  expect(mobile.height).toBeLessThanOrEqual(165);
  expect(mobile.cardHeight).toBeGreaterThanOrEqual(44);
  const first = dashboard.locator('.mission-cell').first();
  for (const selector of ['.mission-name', '.mission-target', '.mission-time', '.mission-flag']) {
    await expect(first.locator(selector)).toBeVisible();
  }
  await page.setViewportSize({width: 1280, height: 900});
  const desktop = await dimensions();
  expect(desktop.width).toBe(164);
  expect(desktop.cardHeight).toBe(134);
});

test('full-color icons keep accessible names, mission numbers, data and completion behavior', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await open(page);
  const dashboard = await importFile(page);
  const first = dashboard.locator('.mission-cell').first();
  await expect(first.locator('.mission-name img')).toHaveAttribute('data-icon-file', 'afx_ship_henerprise.png');
  await expect(first.locator('.mission-target img')).toHaveAttribute('data-icon-file', 'afx_tungsten_ankh_4.png');
  await expect(first.locator('.mission-name img')).toHaveAttribute('alt', /Henerprise.*henerprise-1/);
  await expect(first.locator('.mission-target img')).toHaveAttribute('alt', /Tungsten Ankh/);
  await expect(first).toHaveAttribute('aria-label', /Mission 1.*henerprise-1/);
  await expect(first.locator('.mission-number')).toHaveText('#1S');
  const before = await page.evaluate(async () => (await (await import('./store.mjs')).readActivePlan()).data);
  const images = await first.locator('img').evaluateAll(elements => elements.map(image => image.src));
  async function unfiltered() {
    return first.locator('img').evaluateAll(images => images.every(image => {
      for (let node = image; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.filter !== 'none' || style.opacity !== '1') return false;
      }
      const size = image.getBoundingClientRect();
      return size.width >= 32 && size.width <= 36 && size.height >= 32 && size.height <= 36 && image.naturalWidth > 0;
    }));
  }
  await first.hover(); await expect.poll(unfiltered).toBe(true);
  await first.locator('.mission-target img').click();
  await expect(first).toHaveClass(/latest-completed/);
  await expect.poll(unfiltered).toBe(true);
  const iconTops = await first.locator('img').evaluateAll(images => images.map(image => image.getBoundingClientRect().top));
  expect(Math.abs(iconTops[0] - iconTops[1])).toBeLessThan(1);
  expect((await first.boundingBox()).height).toBeLessThanOrEqual(140);
  await dashboard.locator('.mission-cell').last().click();
  await expect(first).toHaveClass(/done/); await expect(first).not.toHaveClass(/latest-completed/);
  await first.hover(); await expect.poll(unfiltered).toBe(true);
  expect(await first.locator('img').evaluateAll(elements => elements.map(image => image.src))).toEqual(images);
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  expect(await page.evaluate(async () => (await (await import('./store.mjs')).readActivePlan()).data)).toEqual(before);
  await dashboard.locator('#slotFilter').selectOption('2');
  await expect(dashboard.locator('.mission-cell')).toHaveCount(1);
  await expect(dashboard.locator('.mission-number')).toHaveText('#2S');
});

test('missing and failed artwork shows readable fallback; ranked targets use highest artwork', async ({page}) => {
  await open(page);
  const html = fs.readFileSync(path.join(fixtures, 'first.html'), 'utf8');
  const data = JSON.parse(html.split('const data=')[1].split(';\ndocument.getElementById')[0]);
  data.schedule[0].ship = 'future-ship-3'; data.schedule[0].target = 'future-material';
  data.schedule[1].target = 'geode-1';
  await page.locator('#planFile').setInputFiles({name: 'fallback.html', mimeType: 'text/html',
    buffer: Buffer.from('<script>const data=' + JSON.stringify(data) + ';</script>')});
  const dashboard = page.frameLocator('#dashboard');
  const first = dashboard.locator('.mission-cell').first();
  await expect(first.locator('.mission-name')).toHaveText('future-ship-3');
  await expect(first.locator('.mission-target')).toHaveText('future-material');
  await expect(first.locator('.mission-number')).toHaveText('#1E');
  const material = dashboard.locator('.mission-target img').last();
  await expect(material).toHaveAttribute('data-icon-file', 'afx_tau_ceti_geode_3.png');
  await material.evaluate(image => { image.src = 'data:image/png;base64,broken'; });
  await expect(dashboard.locator('.mission-target').last()).toHaveText('geode-1');
  await first.click(); await expect(first).toHaveClass(/latest-completed/);
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
});

test('local Henliner artwork and colored duration badges agree across checklist and ship displays', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await open(page);
  const dashboard = await importFile(page, 'henliner');
  const original = await page.evaluate(async () => (await import('./store.mjs')).readActivePlan());
  for (const [suffix, letter, name, color] of [[1, 'S', 'Short', 'rgb(37, 99, 235)'],
    [2, 'M', 'Standard', 'rgb(124, 58, 237)'], [3, 'E', 'Extended', 'rgb(194, 65, 12)']]) {
    const cell = dashboard.locator('.mission-cell[data-mission*="|henliner-' + suffix + '|"]');
    const image = cell.locator('.mission-name img'), badge = cell.locator('.mission-length-badge');
    await expect(image).toHaveAttribute('data-icon-file', 'afx_ship_atreggies.png');
    await expect(image).toHaveAttribute('alt', /Atreggies Henliner/);
    await expect.poll(() => image.evaluate(element => element.naturalWidth)).toBe(64);
    await expect(badge).toHaveText(letter); await expect(badge).toHaveAttribute('aria-label', name + ' mission');
    expect(await badge.evaluate(element => getComputedStyle(element).backgroundColor)).toBe(color);
    await expect(cell).toHaveAttribute('aria-label', new RegExp(name + ' mission'));
    const related = dashboard.locator('.ship-display').filter({hasText: 'henliner-' + suffix});
    await expect(related).toHaveCount(2); // aggregate ship card and detailed schedule
    await expect(related.locator('img[data-icon-file="afx_ship_atreggies.png"]')).toHaveCount(2);
    for (const item of await related.locator('.mission-length-badge').all()) {
      await expect(item).toHaveText(letter);
      expect(await item.evaluate(element => getComputedStyle(element).backgroundColor)).toBe(color);
    }
  }
  const first = dashboard.locator('.mission-cell').first();
  await first.locator('.mission-length-badge').click();
  await expect(first).toHaveClass(/latest-completed/);
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  const saved = await page.evaluate(async () => (await import('./store.mjs')).readActivePlan());
  expect(saved.data).toEqual(original.data); expect(saved.keys).toEqual(original.keys);
  expect(await first.locator('.mission-length-badge').evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgb(37, 99, 235)');
  await page.reload();
  await expect(first).toHaveClass(/latest-completed/);
  await expect(first.locator('.completion-time')).toHaveText('Just now');
  expect(await page.evaluate(async () => (await (await import('./store.mjs')).readActivePlan()).completionTimes)).toEqual(saved.completionTimes);
  await first.locator('.mission-name img').evaluate(image => { image.src = 'data:image/png;base64,broken'; });
  await expect(first.locator('.mission-name')).toHaveText('henliner-1');
  await first.click();
  await expect(first).not.toHaveClass(/done/);
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
});

test('timestamp-only backup updates synchronize across windows and invalid dates are rejected', async ({page, context}) => {
  await open(page);
  const dashboard = await importFile(page);
  await dashboard.locator('.mission-cell').nth(0).click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await dashboard.locator('.mission-cell').nth(1).click();
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  const record = await page.evaluate(async () => (await import('./store.mjs')).readActivePlan());
  const other = await context.newPage(); await other.goto('./');
  const otherDashboard = other.frameLocator('#dashboard');
  await expect(otherDashboard.locator('.mission-cell.done')).toHaveCount(2);
  const firstKey = await dashboard.locator('.mission-cell').nth(0).getAttribute('data-mission');
  const backup = {format: 'reggference-progress-v1', plan: record.storageKey, completed: record.progress,
    completionTimes: {...record.completionTimes, [firstKey]: Date.now() + 1000}};
  await dashboard.locator('#progressFile').setInputFiles({name: 'times.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(backup))});
  await expect(page.locator('#saveStatus')).toHaveText('Saved on this device');
  await expect(dashboard.locator('.mission-cell.latest-completed')).toHaveAttribute('data-mission', firstKey);
  await expect(otherDashboard.locator('.mission-cell.latest-completed')).toHaveAttribute('data-mission', firstKey);
  const before = await page.evaluate(async () => (await import('./store.mjs')).readActivePlan());
  backup.completionTimes[firstKey] = 'yesterday';
  await dashboard.locator('#progressFile').setInputFiles({name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(backup))});
  await expect(page.locator('#message')).toContainText('Invalid completion timestamps');
  expect(await page.evaluate(async () => (await import('./store.mjs')).readActivePlan())).toEqual(before);
});

test('PWA manifest meets Chromium installability requirements', async ({baseURL}) => {
  // Installation is intentionally disabled in Playwright's incognito contexts.
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'mission-plan-install-'));
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ||
    (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined);
  let context;
  try {
    context = await chromium.launchPersistentContext(profile, {headless: true, executablePath});
    const page = context.pages()[0];
    await page.goto(baseURL);
    await expect(page.locator('#offlineStatus')).toHaveText('Ready offline');
    const session = await context.newCDPSession(page);
    const result = await session.send('Page.getInstallabilityErrors');
    expect(result.installabilityErrors).toEqual([]);
  } finally {
    await context?.close();
    fs.rmSync(profile, {recursive: true, force: true});
  }
});
