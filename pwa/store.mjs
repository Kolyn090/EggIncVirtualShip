// Exactly one key. There is no saved-plan collection, history, or migration.
const DATABASE = 'egginc-active-mission-plan';
const STORE = 'state';
const ACTIVE = 'active';
let database;

export class PlanStateError extends Error {}

function openDatabase() {
  database ??= new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => { db.close(); database = undefined; };
      resolve(db);
    };
    request.onerror = () => { database = undefined; reject(request.error); };
  });
  return database;
}

async function transaction(mode, operation) {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    let tx;
    try { tx = db.transaction(STORE, mode, {durability: 'strict'}); }
    catch { tx = db.transaction(STORE, mode); }
    let result, failure;
    const store = tx.objectStore(STORE);
    const request = store.get(ACTIVE);
    request.onsuccess = () => {
      try { result = operation(store, request.result); }
      catch (error) { failure = error; tx.abort(); }
    };
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(failure || tx.error || new Error('Local storage failed.'));
    tx.onabort = () => reject(failure || tx.error || new Error('Local storage was interrupted.'));
  });
}

export function readActivePlan() {
  return transaction('readonly', (_, record) => record || null);
}

export function importPlan(data, name, identity) {
  return transaction('readwrite', (store, existing) => {
    if (existing) throw new PlanStateError('Close the current plan before importing another plan.');
    const record = {id: crypto.randomUUID(), name, data, storageKey: identity.storageKey,
      keys: identity.keys, progress: [], completionTimes: {}, revision: 0};
    store.add(record, ACTIVE); // atomic across windows; never overwrites a plan
    return record;
  });
}

export function saveProgress(id, add, remove, completionTimes) {
  return transaction('readwrite', (store, record) => {
    if (!record || record.id !== id) throw new PlanStateError('This plan is no longer active.');
    const keys = new Set(record.keys);
    if (![add, remove].every(list => Array.isArray(list) && list.length <= keys.size && list.every(key => keys.has(key)))) {
      throw new Error('Invalid checklist update.');
    }
    const completed = new Set(record.progress);
    const times = {...record.completionTimes};
    if (completionTimes !== undefined && (!completionTimes || typeof completionTimes !== 'object' || Array.isArray(completionTimes) ||
        Object.entries(completionTimes).some(([key, value]) => !keys.has(key) ||
          (value !== null && (!Number.isFinite(value) || value <= 0 || value > 8640000000000000))))) {
      throw new Error('Invalid completion timestamps.');
    }
    for (const key of remove) completed.delete(key);
    for (const key of add) {
      if (!completed.has(key)) times[key] = completionTimes === undefined ? Date.now() : completionTimes[key];
      completed.add(key);
    }
    // Explicit backup imports can restore known timestamps for retained checks.
    if (completionTimes) Object.assign(times, completionTimes);
    record.progress = [...completed];
    record.completionTimes = Object.fromEntries(record.progress.filter(key => Number.isFinite(times[key]) && times[key] > 0)
      .map(key => [key, times[key]]));
    record.revision++;
    store.put(record, ACTIVE);
    return record;
  });
}

export function closePlan(id) {
  return transaction('readwrite', (store, record) => {
    if (!record || record.id !== id) throw new PlanStateError('This plan is no longer active.');
    store.delete(ACTIVE); // plan and all checklist progress are one atomic record
  });
}
