// Loads the dashboard's JavaScript the way the page does: one shared global scope,
// files in build order, data constants first. A small DOM stub records what the
// code writes. It proves the code runs and what HTML it produces, not how the
// page looks.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const JS_DIR = path.resolve(HERE, '../../scripts/dashboard');

function element(id) {
  const classes = new Set();
  return {
    id, innerHTML: '', textContent: '', style: {}, dataset: {},
    classList: {
      add: c => classes.add(c), remove: c => classes.delete(c),
      contains: c => classes.has(c),
      toggle: (c, force = !classes.has(c)) => (force ? classes.add(c) : classes.delete(c)),
    },
    addEventListener() {}, removeEventListener() {}, focus() {}, querySelector: () => null,
    querySelectorAll: () => [],
  };
}

export function makeDom() {
  const els = {};
  const byId = id => (els[id] ||= element(id));
  const history = { replaced: [] };
  const location = { hash: '' };
  return {
    els, byId, history, location,
    document: {
      getElementById: byId,
      querySelector: sel => {
        const m = /data-tab="([^"]+)"/.exec(sel);
        return m ? byId('btn-' + m[1]) : null;
      },
      querySelectorAll: () => [],
      addEventListener() {}, removeEventListener() {},
    },
    window: { addEventListener() {} },
    historyApi: { replaceState: (_s, _t, h) => { history.replaced.push(h); location.hash = h; } },
  };
}

export class ChartStub {
  static instances = [];
  constructor(el, config) { this.el = el; this.config = config; ChartStub.instances.push(this); }
  destroy() {} resize() {} update() {}
  static register() {}
}

// data: SNAPSHOTS, DATES, CURRENT_DATE, ORG, TREND_SERIES, ANNOTATIONS, MOVED, REGION, TREND_START, RANK_WEIGHTS.
// globals: extra names in the page's scope, e.g. a `google` stub for the Apps Script paths.
export function load(files, data = {}, dom = makeDom(), globals = {}) {
  const ctx = vm.createContext({ ...globals,
    console, Math, JSON, Date, Number, String, Object, Array, Set, Map, RegExp, Intl,
    document: dom.document, window: dom.window, location: dom.location, history: dom.historyApi,
    requestAnimationFrame: fn => fn(), setTimeout: fn => fn(), clearTimeout() {}, Chart: ChartStub,
    navigator: { clipboard: { copied: [], writeText(t) { this.copied.push(t); return { then: fn => fn() }; } } },
  });
  const consts = Object.entries({
    SNAPSHOTS: {}, DATES: [], CURRENT_DATE: null, ORG: 'org', PUBLISHED_URL: '', TREND_SERIES: [], ANNOTATIONS: [], MOVED: {}, REGION: 'eu-west-2', TREND_START: '',
    RANK_WEIGHTS: { insp_crit: 10, insp_high: 3, gh_crit: 50, gh_high: 15, code_scan: 5, secret: 100 },
    ...data,
  }).map(([k, v]) => `const ${k} = ${JSON.stringify(v)};`).join('\n');
  vm.runInContext(consts, ctx, { filename: 'data.js' });
  for (const f of files) vm.runInContext(fs.readFileSync(path.join(JS_DIR, f), 'utf8'), ctx, { filename: f });
  return { ctx, dom, run: src => vm.runInContext(src, ctx) };
}

// A real dashboard snapshot (build_dashboard.extract() output, masked fixture),
// with fields overridden per test.
const FIXTURE = JSON.parse(fs.readFileSync(path.resolve(HERE, '../fixtures/pair-a/20261007/snapshot.json'), 'utf8'));
export function snapshot(o = {}) {
  const s = structuredClone(FIXTURE);
  for (const k of ['inspector', 'github', 'correlation']) Object.assign(s[k], o[k] || {});
  return s;
}
