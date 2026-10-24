// Read the generated JSON as text. Never parse imported HTML into a live DOM
// or execute scripts, styles, links, images, or other content from the file.
function jsonObjectEnd(text, start) {
  let depth = 0, quoted = false, escaped = false;
  for (let i = start; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === '"') quoted = false;
    } else if (char === '"') quoted = true;
    else if (char === '{' || char === '[') depth++;
    else if (char === '}' || char === ']') {
      depth--;
      if (depth === 0) return i + 1;
    }
  }
  throw new Error('The plan contains incomplete mission data.');
}

export function validatePlan(data) {
  for (const key of ['schedule', 'launch_plan', 'craft_plan', 'material_balance', 'event_windows']) {
    if (!Array.isArray(data?.[key]) || data[key].some(row => !row || typeof row !== 'object' || Array.isArray(row))) {
      throw new Error('This file is missing optimizer dashboard data: ' + key);
    }
  }
  for (const row of data.schedule) {
    if (typeof row.ship !== 'string' || !row.ship || !Number.isInteger(Number(row.slot)) || Number(row.slot) < 1 ||
        !Number.isFinite(Number(row.start_hour)) || Number(row.start_hour) < 0 ||
        !Number.isFinite(Number(row.end_hour)) || Number(row.end_hour) < Number(row.start_hour) ||
        !['true', 'false'].includes(String(row.event_bonus).toLowerCase()) ||
        (row.target != null && (typeof row.target !== 'string' || !row.target))) {
      throw new Error('This file contains invalid mission data.');
    }
  }
  const identity = progressIdentity(data);
  if (new Set(identity.keys).size !== identity.keys.length) throw new Error('The plan contains duplicate missions.');
  return identity;
}

export function parsePlan(html) {
  let result;
  for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi)) {
    const source = match[1];
    const assignment = /\bconst\s+data\s*=\s*(?=\{)/.exec(source);
    if (!assignment) continue;
    if (result) throw new Error('The file contains more than one plan.');
    const start = assignment.index + assignment[0].length;
    try { result = JSON.parse(source.slice(start, jsonObjectEnd(source, start))); }
    catch { throw new Error('The plan contains invalid or incomplete mission data.'); }
  }
  if (!result) throw new Error('Choose an optimizer-generated HTML dashboard (plan.html).');
  validatePlan(result);
  return result;
}

// This matches the existing dashboard's backup identity exactly. The active
// record gets a separate random ID; reopening the same HTML never restores old
// progress automatically after the previous plan was closed.
export function progressIdentity(data) {
  const num = value => Number(value) || 0;
  const schedule = [...data.schedule].sort((a, b) => num(a.start_hour) - num(b.start_hour) || num(a.slot) - num(b.slot));
  const keys = schedule.map(row => `${num(row.slot)}|${row.ship}|${num(row.start_hour).toFixed(5)}|${num(row.end_hour).toFixed(5)}` +
    ((row.target && row.target !== 'none') ? '|target:' + row.target : ''));
  let hash = 2166136261;
  for (const char of keys.join(';')) {
    // Mission IDs are ASCII in generated plans; use UTF-16 units like the
    // dashboard as well, so custom identifiers preserve backup compatibility.
    for (let i = 0; i < char.length; i++) { hash ^= char.charCodeAt(i); hash = Math.imul(hash, 16777619); }
  }
  return {keys, storageKey: `reggference-done-v2-${data.metadata?.target || 'metronome-4'}-${(hash >>> 0).toString(36)}`};
}
