import {dashboardTemplate} from './dashboard-template.mjs';

const scriptJSON = value => JSON.stringify(value).replaceAll('<', '\\u003c');

export function renderDashboard(record, token) {
  // Only this trusted, bundled template runs. Imported HTML is never executed.
  const setup = `(() => {
    const config = ${scriptJSON({id: record.id, token, key: record.storageKey, progress: record.progress})};
    let progress = config.progress;
    const send = message => parent.postMessage({...message, id: config.id, token: config.token}, '*');
    window.__planBridge = {
      config, send, apply(values) {
        const current = new Set(progress);
        if (values.length === progress.length && values.every(key => current.has(key))) return false;
        progress = [...values]; return true;
      }
    };
    Object.defineProperty(window, 'localStorage', {value: {
      getItem(key) { return key === config.key ? JSON.stringify(progress) : null; },
      setItem(key, value) {
        if (key !== config.key) throw Error('Only the active plan can save progress.');
        const next = JSON.parse(value), previous = new Set(progress), selected = new Set(next);
        const add = next.filter(key => !previous.has(key));
        const remove = progress.filter(key => !selected.has(key));
        progress = [...next];
        send({type: 'progress', add, remove});
      }
    }});
    window.alert = message => send({type: 'notice', message: String(message)});
  })();`;
  const ready = `(() => {
    const bridge = window.__planBridge;
    addEventListener('message', event => {
      if (event.source !== parent || event.data?.token !== bridge.config.token || event.data?.id !== bridge.config.id) return;
      if (event.data.type === 'restore-progress') {
        if (!bridge.apply(event.data.progress)) return;
        const allowed = new Set(sched.map(missionKey));
        completed = new Set(event.data.progress.filter(key => allowed.has(key)));
        drawTimeline(); renderSchedule(); scrollToProgress();
      }
    });
    bridge.send({type: 'ready'});
  })();`;
  const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'">`;
  return dashboardTemplate
    .replace('<head>', '<head>' + policy + '<script>' + setup + '</script>')
    .replace('/*__DATA__*/', scriptJSON(record.data))
    .replace('</body>', '<script>' + ready + '</script></body>');
}
