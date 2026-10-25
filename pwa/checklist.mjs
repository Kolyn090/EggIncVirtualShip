// PWA-only presentation; the trusted standalone dashboard stays unchanged.
export const checklistStyles = `
.mission-cell:hover{filter:none}
.mission-identity{display:flex;align-items:center;flex-wrap:wrap;gap:4px;padding-right:12px}
.mission-identity .mission-name,.mission-identity .mission-target{display:flex;align-items:center;padding:0;line-height:1.2;max-width:100%}
.mission-icon{display:block;width:34px;height:34px;object-fit:contain;filter:none;opacity:1;mix-blend-mode:normal}
.mission-number{display:flex;flex-direction:column;gap:2px;flex:0 0 24px;font-size:10px;font-weight:700;line-height:1.1;overflow-wrap:anywhere}
.mission-length-badge{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;width:18px;height:18px;border-radius:5px;font-size:11px;font-weight:800;line-height:1;color:#fff;background:#475569;vertical-align:middle}
.mission-length-badge.short{background:#2563eb}
.mission-length-badge.standard{background:#7c3aed}
.mission-length-badge.extended{background:#c2410c}
.ship-display{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.related-ship-icon{width:32px;height:32px}
.mission-identity .icon-fallback{font-size:11px;overflow-wrap:anywhere}
.mission-cell.done.latest-completed{background:#f4d66b;border-color:#ffe394;color:#29250f}
.mission-cell.done.latest-completed::after{color:#6b4f00}
.mission-cell.done.latest-completed .mission-time{color:#493b10}
.completion-time{display:block;font-size:11px;line-height:1.3;margin-top:4px;color:#c2efdf}
.latest-completed .completion-time{color:#493b10}
.table-done.latest-completed{background:#f4d66b;border-color:#ffe394;color:#29250f}
@media(max-width:650px){
  .timeline-list{gap:10px}.checklane{padding:6px;border-radius:10px}
  .lane-header{gap:6px;margin-bottom:4px}.lane-header strong{font-size:14px}
  .mission-scroll{gap:6px;padding:3px 2px 5px;min-height:0}
  .mission-cell{flex-basis:128px;min-height:108px;padding:7px 8px;border-radius:9px;gap:3px}
  .mission-cell .mission-name{font-size:12px;line-height:1.2}
  .mission-cell .mission-target{font-size:11px;line-height:1.25}
  .mission-cell .mission-time,.mission-cell .mission-flag{line-height:1.25}
  .mission-icon{width:32px;height:32px}
  .mission-cell.done::after{right:6px;top:4px;font-size:18px}
  .completion-time{font-size:10px;margin-top:2px}
  .lane-gap{flex-basis:82px;padding:6px}
  .table-done,.table-undone{min-height:44px}
}`;

// Self-contained so it can run inside the offline, opaque-origin frame.
export function installChecklist() {
  const bridge = window.__planBridge;
  const missions = new Map(sched.map((mission, index) => [missionKey(mission), {mission, number: index + 1}]));
  function durationFor(ship) {
    return ({0: ['Tutorial', 'T', 'tutorial'], 1: ['Short', 'S', 'short'],
      2: ['Standard', 'M', 'standard'], 3: ['Extended', 'E', 'extended']})[/-(\d+)$/.exec(ship)?.[1]];
  }
  function durationBadge(duration) {
    const badge = document.createElement('span');
    badge.className = 'mission-length-badge ' + duration[2]; badge.textContent = duration[1];
    badge.title = duration[0] + ' mission'; badge.setAttribute('aria-label', duration[0] + ' mission');
    return badge;
  }
  function decorateShipDisplays() {
    const labels = [...document.querySelectorAll('.shipcard .name'),
      ...[...document.querySelectorAll('#scheduleRows tr')].map(row => row.children.length === 7 ? row.children[3] : null).filter(Boolean)];
    for (const label of labels) {
      if (label.querySelector('.ship-display')) continue;
      const ship = label.textContent, icon = bridge.config.icons.ships[ship];
      const display = document.createElement('span'); display.className = 'ship-display';
      if (icon && bridge.config.icons.images[icon.file]) {
        const image = document.createElement('img'); image.className = 'mission-icon related-ship-icon';
        image.alt = icon.label; image.width = image.height = 32; image.dataset.iconFile = icon.file;
        image.addEventListener('error', () => image.remove(), {once: true});
        image.src = bridge.config.icons.images[icon.file]; display.append(image);
      }
      const name = document.createElement('span'); name.textContent = ship; display.append(name);
      const duration = durationFor(ship); if (duration) display.append(durationBadge(duration));
      label.replaceChildren(display);
    }
  }
  function decorateIcons() {
    document.querySelectorAll('.mission-cell').forEach(cell => {
      const {mission, number} = missions.get(cell.dataset.mission);
      const duration = durationFor(mission.ship);
      const ship = cell.querySelector('.mission-name'), target = cell.querySelector('.mission-target');
      function artwork(span, icon, fallback, name) {
        span.title = name;
        const source = icon && bridge.config.icons.images[icon.file];
        const textFallback = () => { span.replaceChildren(document.createTextNode(fallback)); span.classList.add('icon-fallback'); };
        if (!source) { textFallback(); return; }
        const image = document.createElement('img'); image.className = 'mission-icon';
        image.alt = name; image.width = 34; image.height = 34;
        image.dataset.iconFile = icon.file;
        image.addEventListener('error', textFallback, {once: true});
        image.src = source;
        span.replaceChildren(image);
      }
      const shipIcon = bridge.config.icons.ships[mission.ship];
      artwork(ship, shipIcon, mission.ship, (shipIcon?.label || mission.ship) + ' (' + mission.ship + ')');
      const targetIcon = bridge.config.icons.targets[mission.target || 'none'];
      artwork(target, targetIcon, targetNameFor(mission), 'Target: ' + targetNameFor(mission) +
        (targetIcon ? ' (highest-tier artwork)' : ''));
      const identity = document.createElement('span'); identity.className = 'mission-identity';
      const index = document.createElement('span'); index.className = 'mission-number';
      index.append(document.createTextNode('#' + number));
      if (duration) index.append(durationBadge(duration));
      identity.append(index, ship, target); cell.prepend(identity);
      cell.setAttribute('aria-label', 'Mission ' + number + '. ' + (duration ? duration[0] + ' mission. ' : '') + cell.title);
    });
  }
  function relativeTime(timestamp, now = Date.now()) {
    if (!Number.isFinite(timestamp) || timestamp <= 0) return 'Completion time unavailable';
    const date = new Date(timestamp), today = new Date(now);
    const elapsed = Math.max(0, now - timestamp);
    if (elapsed < 60000) return 'Just now';
    if (elapsed < 3600000) return Math.floor(elapsed / 60000) + ' min ago';
    const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    const time = date.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
    if (date.toDateString() === today.toDateString()) return 'Today, ' + time;
    if (date.toDateString() === yesterday.toDateString()) return 'Yesterday, ' + time;
    return date.toLocaleDateString([], {year: 'numeric', month: 'short', day: 'numeric'}) + ', ' + time;
  }
  function decorate() {
    let latest = null, latestTime = -1;
    for (const key of completed) {
      const time = bridge.completionTimes[key] || 0;
      if (time >= latestTime) { latest = key; latestTime = time; }
    }
    document.querySelectorAll('[data-mission]').forEach(cell => {
      const key = cell.dataset.mission, done = completed.has(key);
      cell.classList.toggle('latest-completed', done && key === latest);
      let label = cell.querySelector('.completion-time');
      if (!done) { label?.remove(); return; }
      if (!label) {
        label = document.createElement('span'); label.className = 'completion-time';
        cell.append(label);
      }
      label.textContent = relativeTime(bridge.completionTimes[key]);
      label.title = bridge.completionTimes[key] ? new Date(bridge.completionTimes[key]).toLocaleString() : 'No timestamp was recorded for this older completion';
      label.setAttribute('aria-label', (key === latest ? 'Most recently completed. ' : 'Completed. ') + label.textContent);
    });
  }
  const draw = drawTimeline, render = renderSchedule, ships = renderShips;
  drawTimeline = () => { draw(); decorateIcons(); decorate(); };
  renderSchedule = () => { render(); decorateShipDisplays(); decorate(); };
  renderShips = () => { ships(); decorateShipDisplays(); };
  decorateIcons(); decorateShipDisplays(); decorate();
  setInterval(decorate, 15000);
  addEventListener('focus', decorate);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) decorate(); });

  // Keep the v1 format/identity and add optional timestamps. Old importers ignore
  // this field; old backups remain valid and never invent completion dates.
  document.getElementById('exportProgress').addEventListener('click', event => {
    event.stopImmediatePropagation();
    const contents = JSON.stringify({format: 'reggference-progress-v1', plan: storageKey,
      completed: [...completed], completionTimes: bridge.completionTimes}, null, 2);
    const url = URL.createObjectURL(new Blob([contents], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = 'reggference-progress.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, true);
  document.getElementById('progressFile').addEventListener('change', async event => {
    event.stopImmediatePropagation();
    const file = event.target.files?.[0]; if (!file) return;
    try {
      const obj = JSON.parse(await file.text());
      if (obj.format !== 'reggference-progress-v1' || obj.plan !== storageKey || !Array.isArray(obj.completed)) {
        throw Error('Progress file belongs to a different launch plan or has an invalid format');
      }
      const allowed = new Set(sched.map(missionKey));
      const values = obj.completionTimes;
      if (values !== undefined && (!values || typeof values !== 'object' || Array.isArray(values) ||
          Object.values(values).some(time => !Number.isFinite(time) || time <= 0 || time > 8640000000000000))) {
        throw Error('Invalid completion timestamps');
      }
      bridge.importTimes = values || {};
      completed = new Set(obj.completed.filter(key => allowed.has(key)));
      saveProgress(); drawTimeline(); renderSchedule(); scrollToProgress();
      alert('Progress imported.');
    } catch (error) { alert('Could not import: ' + error.message); }
    finally { bridge.importTimes = null; event.target.value = ''; }
  }, true);
}
