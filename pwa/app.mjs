import {parsePlan, validatePlan} from './plan.mjs';
import {readActivePlan, importPlan, saveProgress, closePlan, PlanStateError} from './store.mjs';
import {renderDashboard} from './frame.mjs';

const $ = id => document.getElementById(id);
let frame = $('dashboard');
let active = null, token = null, ready = false, loading = true, importing = false, closing = false;
let pendingClose = null, saving = false, operations = [], refreshSequence = 0;
const channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('egginc-active-plan') : null;

function message(text = '', error = false) {
  $('message').textContent = text;
  $('message').classList.toggle('error', error);
}

function controls() {
  $('importScreen').hidden = loading || !!active;
  $('activeToolbar').hidden = !active;
  $('choosePlan').disabled = loading || importing || !!active;
  $('planFile').disabled = loading || importing || !!active;
  $('closeCurrent').disabled = closing;
}

function sendProgress() {
  if (active && ready && !saving && !operations.length) {
    frame.contentWindow.postMessage({type: 'restore-progress', id: active.id, token, progress: active.progress,
      completionTimes: active.completionTimes || {}}, '*');
  }
}

function notifyChange() {
  channel?.postMessage('changed');
  // Fallback for browsers without BroadcastChannel. This contains no plan or
  // progress, and is never used as the active-plan source of truth.
  try { localStorage.setItem('egginc-plan-change', crypto.randomUUID()); } catch {}
}

async function refresh() {
  const sequence = ++refreshSequence;
  try {
    const record = await readActivePlan();
    if (sequence !== refreshSequence) return;
    loading = false;
    if (record?.id === active?.id) {
      active = record;
      sendProgress();
      controls();
      return;
    }
    if ($('closeDialog').open) $('closeDialog').close();
    pendingClose = null;
    active = record; token = null; ready = false; operations = [];
    // Discard the old browsing context as well as its document. Reusing srcdoc
    // navigations would leave old dashboards in the iframe's back history.
    const replacement = document.createElement('iframe');
    replacement.id = 'dashboard'; replacement.title = 'Active mission dashboard';
    replacement.setAttribute('sandbox', 'allow-scripts allow-downloads');
    replacement.hidden = !record;
    frame.replaceWith(replacement); frame = replacement;
    controls();
    if (!record) {
      frame.srcdoc = '';
      $('saveStatus').textContent = '';
      $('planName').textContent = '';
      $('retrySave').hidden = true;
      return;
    }
    $('planName').textContent = record.name;
    $('saveStatus').textContent = 'Opening saved plan…';
    const identity = validatePlan(record.data);
    if (record.storageKey !== identity.storageKey || JSON.stringify(record.keys) !== JSON.stringify(identity.keys) || !Array.isArray(record.progress) ||
        record.progress.some(key => !identity.keys.includes(key))) {
      throw new Error('The saved plan could not be read. Close Current Plan to remove it.');
    }
    token = crypto.randomUUID();
    frame.srcdoc = renderDashboard(record, token);
  } catch (error) {
    // Never interpret a storage/read error as permission to replace a plan.
    if (sequence === refreshSequence) message('Could not open local plan storage: ' + error.message, true);
  }
}

async function flushProgress() {
  if (saving || !active || !operations.length) return;
  saving = true;
  $('retrySave').hidden = true;
  $('saveStatus').textContent = 'Saving checklist…';
  try {
    while (operations.length && active && !closing) {
      const operation = operations[0];
      const record = await saveProgress(operation.id, operation.add, operation.remove, operation.completionTimes);
      if (active?.id !== operation.id) return;
      active = record;
      operations.shift();
      notifyChange();
    }
    if (!operations.length && active) $('saveStatus').textContent = 'Saved on this device';
  } catch (error) {
    if (error instanceof PlanStateError) {
      operations = [];
      await refresh();
    } else {
      $('saveStatus').textContent = 'Checklist could not be saved';
      $('retrySave').hidden = false;
      message('Keep the app open and retry saving, or export a progress backup from the dashboard. ' + error.message, true);
    }
  } finally {
    saving = false;
    if (!operations.length) await refresh();
  }
}

addEventListener('message', event => {
  const data = event.data;
  if (!active || closing || event.source !== frame.contentWindow || data?.id !== active.id || data?.token !== token) return;
  if (data.type === 'ready') {
    ready = true;
    $('saveStatus').textContent = 'Saved on this device';
    sendProgress();
  } else if (data.type === 'progress') {
    const keys = new Set(active.keys);
    if (![data.add, data.remove].every(list => Array.isArray(list) && list.length <= keys.size && list.every(key => keys.has(key)))) return;
    operations.push({id: active.id, add: data.add, remove: data.remove, completionTimes: data.completionTimes});
    void flushProgress();
  } else if (data.type === 'notice') message(String(data.message).slice(0, 1000));
});

$('choosePlan').addEventListener('click', () => {
  if (!active && !loading && !importing) $('planFile').click();
});
$('planFile').addEventListener('change', async event => {
  // UI guards AND an atomic database add are required: another window can
  // activate a plan while this window is still reading the selected file.
  if (active || loading || importing) {
    event.target.value = '';
    message('Close the current plan before importing another plan.', true);
    return;
  }
  const file = event.target.files?.[0];
  if (!file) return;
  importing = true; controls(); message();
  try {
    const data = parsePlan(await file.text());
    const identity = validatePlan(data);
    await importPlan(data, file.name, identity);
    notifyChange();
    await refresh();
  } catch (error) {
    message(error.message, true);
    if (error instanceof PlanStateError) await refresh();
  } finally {
    event.target.value = '';
    importing = false; controls();
  }
});

$('closeCurrent').addEventListener('click', () => {
  if (!active || closing) return;
  pendingClose = active.id;
  $('closeDialog').showModal();
});
$('keepPlan').addEventListener('click', () => {
  pendingClose = null; $('closeDialog').close();
});
$('confirmClose').addEventListener('click', async () => {
  const id = pendingClose;
  if (!id || closing) return;
  closing = true; $('confirmClose').disabled = true; controls();
  try {
    await closePlan(id);
    operations = [];
    message();
    notifyChange();
    await refresh();
  } catch (error) {
    message('Could not close the plan: ' + error.message, true);
    await refresh();
  } finally {
    closing = false; $('confirmClose').disabled = false; controls();
    $('closeDialog').close(); pendingClose = null;
    if (active && operations.length) void flushProgress();
  }
});
$('retrySave').addEventListener('click', () => { message(); void flushProgress(); });
$('retryStorage').addEventListener('click', () => { message(); void refresh(); });
channel?.addEventListener('message', () => { void refresh(); });
addEventListener('storage', event => { if (event.key === 'egginc-plan-change') void refresh(); });
addEventListener('focus', () => { void refresh(); });
addEventListener('pageshow', () => { void refresh(); });
document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
addEventListener('dragover', event => event.preventDefault());
addEventListener('drop', event => {
  event.preventDefault();
  if (active) message('Close the current plan before importing another plan.', true);
});

controls();
void refresh();
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('./sw.js').then(() => navigator.serviceWorker.ready).then(() => {
    $('offlineStatus').textContent = 'Ready offline';
  }).catch(() => { $('offlineStatus').textContent = 'Offline access unavailable'; });
} else $('offlineStatus').textContent = 'Offline access requires HTTPS or localhost in a supported browser';
