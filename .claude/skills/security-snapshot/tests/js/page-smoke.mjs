// Run a built page's script, exactly as inlined, under the DOM stub: first paint,
// every tab, every snapshot. Usage: node page-smoke.mjs <script.js>
// Prints one JSON line of what it observed; any exception fails the run.
import fs from 'node:fs';
import vm from 'node:vm';
import { makeDom, ChartStub } from './harness.mjs';

const dom = makeDom();
dom.byId('tab-moved').classList.add('active');  // the default tab in the HTML
// switchTab clears every pane and button through querySelectorAll; return them,
// or no pane ever goes inactive and a redraw cannot be told from first paint.
const TABS = ['moved', 'breakdown', 'trend'];
dom.document.querySelectorAll = sel => (sel === '.tab-pane' ? TABS.map(t => dom.byId('tab-' + t))
  : sel === '.tab-btn' ? TABS.map(t => dom.byId('btn-' + t)) : []);
const ctx = vm.createContext({
  console, document: dom.document, window: dom.window, location: dom.location, history: dom.historyApi,
  requestAnimationFrame: fn => fn(), setTimeout: fn => fn(), clearTimeout() {}, Chart: ChartStub, navigator: {},
});
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx, { filename: 'page.js' });
const run = src => vm.runInContext(src, ctx);

const seen = { charts_on_paint: ChartStub.instances.length, paint_charts: ChartStub.instances.map(c => c.el.id), tabs: {}, dates: [] };
let before = 0;
for (const tab of ['breakdown', 'trend', 'moved']) {
  before = ChartStub.instances.length;
  run(`switchTab(document.getElementById('btn-${tab}'), '${tab}')`);
  seen.tabs[tab] = dom.history.replaced.at(-1);
}
seen.moved_current = dom.els.movedPanel.innerHTML;
seen.moved_active = dom.byId('tab-moved').classList.contains('active') && !dom.byId('tab-trend').classList.contains('active');
// Only the charts the return to What moved drew: first paint does not count.
seen.moved_charts = ChartStub.instances.slice(before).filter(c => String(c.el && c.el.id).startsWith('mv')).map(c => c.el.id);
for (const d of run('DATES')) {
  run(`loadDate('${d}')`);
  seen.dates.push(d);
}
seen.charts_total = ChartStub.instances.length;
seen.kpi = dom.els.kpiRow.innerHTML.length;
process.stdout.write(JSON.stringify(seen) + '\n');
