import test from 'node:test';
import assert from 'node:assert/strict';
import { load, snapshot, ChartStub } from './harness.mjs';

const FILES = ['core.js', 'app.js', 'moved.js'];
const two = (curr, prev) => load(FILES, {
  SNAPSHOTS: { '20261021': curr, '20261007': prev }, DATES: ['20261021', '20261007'], CURRENT_DATE: '20261021',
});

test('fmtDate formats a slug', () => {
  assert.equal(two(snapshot(), snapshot()).run("fmtDate('20261021')"), '2026-10-21');
});

test('renderAll fills the KPI row, the secrets banner and the What moved tab', () => {
  const { run, dom } = two(snapshot({ github: { secrets_total: 3 } }), snapshot());
  run('renderAll()');
  assert.match(dom.els.kpiRow.innerHTML, /GH Security Total/);
  assert.match(dom.els.secretsBanner.innerHTML, /3 open secret scanning alerts/);
  assert.match(dom.els.movedPanel.innerHTML, /No comparison for 2026-10-21/);
});

test('the URL carries tab and snapshot, and a link restores both', () => {
  const { run, dom } = two(snapshot(), snapshot());
  run("switchTab(document.getElementById('btn-trend'), 'trend')");
  assert.equal(dom.history.replaced.at(-1), '#trend/20261021');
  run("applyHash('#breakdown/20261007')");
  assert.equal(run('activeDate'), '20261007');
  assert.equal(run('currentTab'), 'breakdown');
  assert.equal(dom.els.snapDisplay.textContent, '2026-10-07');
});

test('an unknown tab or snapshot in the URL changes nothing', () => {
  const { run } = two(snapshot(), snapshot());
  run("applyHash('#admin/20991231')");
  assert.equal(run('activeDate'), '20261021');
  assert.equal(run('currentTab'), 'moved');  // What moved is the default tab
});

test('an old Executive Summary link opens the default tab on its snapshot', () => {
  const { run } = two(snapshot(), snapshot());
  run("applyHash('#exec/20261007')");
  assert.equal(run('activeDate'), '20261007');
  assert.equal(run('currentTab'), 'moved');
});

test('the date modal lists every snapshot, loads the picked one and closes', () => {
  const { run, dom } = two(snapshot(), snapshot());
  run('openDateModal()');
  assert.ok(dom.els.dateModal.classList.contains('open'));
  const body = dom.els.dateModalBody.innerHTML;
  assert.match(body, /data-date="20261021"[\s\S]*Latest[\s\S]*Current/);
  assert.match(body, /data-date="20261007"/);
  assert.match(dom.els.dateModalFooter.innerHTML, /id="loadSnapBtn"[\s\S]*disabled/);  // nothing new picked yet
  run("selectModalDate('20261007')");
  assert.equal(dom.els.loadSnapBtn.disabled, false);
  run('confirmLoadDate()');
  assert.equal(run('activeDate'), '20261007');
  assert.ok(!dom.els.dateModal.classList.contains('open'));
});

test('confirming the snapshot already loaded does nothing', () => {
  const { run, dom } = two(snapshot(), snapshot());
  run('openDateModal(); confirmLoadDate()');
  assert.equal(run('activeDate'), '20261021');
  assert.ok(dom.els.dateModal.classList.contains('open'));
});

test('Escape and a click on the overlay close the modal; a click inside does not', () => {
  const { run, dom } = two(snapshot(), snapshot());
  run('openDateModal()');
  run("handleOverlayClick({ target: document.getElementById('dateModalBody') })");
  assert.ok(dom.els.dateModal.classList.contains('open'));
  run("handleOverlayClick({ target: document.getElementById('dateModal') })");
  assert.ok(!dom.els.dateModal.classList.contains('open'));
  run("openDateModal(); handleModalKeydown({ key: 'a' })");
  assert.ok(dom.els.dateModal.classList.contains('open'));
  run("handleModalKeydown({ key: 'Escape' })");
  assert.ok(!dom.els.dateModal.classList.contains('open'));
});

test('with one snapshot the modal says so and offers no load button', () => {
  const { run, dom } = load(FILES, { SNAPSHOTS: { '20261021': snapshot() }, DATES: ['20261021'], CURRENT_DATE: '20261021' });
  run('openDateModal()');
  assert.match(dom.els.dateModalBody.innerHTML, /Only one snapshot is available/);
  assert.doesNotMatch(dom.els.dateModalFooter.innerHTML, /loadSnapBtn/);
});

test('the picker marks the 30-day basis of the loaded snapshot and the snapshots with a note', () => {
  const dates = ['20261021', '20261007', '20260909'];
  const entry = (basis, kind, note) => ({ basis, kind, file: 'f', detail: 'full', on_disk: true,
    view: { verdict: null, warnings: [], waterfall: null, note: note ? { lead: 'x', cards: [] } : null } });
  const { run, dom } = load(FILES, {
    SNAPSHOTS: Object.fromEntries(dates.map(d => [d, snapshot()])), DATES: dates, CURRENT_DATE: '20261021',
    MOVED: { '20261021': [entry('20261007', 'previous', true), entry('20260909', '30-day', false)],
             '20261007': [entry('20260909', 'previous', false)] },
  });
  run('openDateModal()');
  const row = d => dom.els.dateModalBody.innerHTML.split('date-list-item').find(r => r.includes(`data-date="${d}"`));
  assert.match(row('20261021'), /Latest[\s\S]*Current[\s\S]*dtag-note"[^>]*>Note/);
  assert.doesNotMatch(row('20261021'), /30-day basis/);
  assert.match(row('20260909'), /dtag-basis"[^>]*>30-day basis/);
  assert.doesNotMatch(row('20261007'), /30-day basis|Note/);
  run("closeDateModal(); loadDate('20261007'); openDateModal()");
  assert.doesNotMatch(dom.els.dateModalBody.innerHTML, /30-day basis/);  // 7 Oct has no 30-day comparison
});

const trendRow = (date, n) => ({ date, insp_crit: n, insp_high: 10 * n, unique_cves: n, gh_total: 100 + n, gh_vuln: 50 + n,
  gh_code: 5 + n, gh_secrets: 0, gh_sev_critical: 1, gh_sev_high: 1, gh_sev_medium: 1, gh_sev_low: 1, zone_a_cves: 7, zone_a_pkgs: 9 });
const DATES3 = ['20261021', '20261007', '20260909', '20260512'];
const withTrend = (extra = {}) => load(FILES, {
  SNAPSHOTS: Object.fromEntries(DATES3.map(d => [d, snapshot()])), DATES: DATES3, CURRENT_DATE: '20261021',
  TREND_SERIES: [trendRow('20260512', 900), trendRow('20260909', 30), trendRow('20261007', 40), trendRow('20261021', 20)],
  MOVED: { '20261021': [{ basis: '20261007', kind: 'previous', file: 'f', detail: 'full', on_disk: true, view: { warnings: [] } },
                        { basis: '20260909', kind: '30-day', file: 'g', detail: 'full', on_disk: false, view: { warnings: [] } }] },
  ...extra,
});

test('the GH total KPI compares with the 30-day basis What moved uses, and says when there is none', () => {
  const { run, dom } = withTrend();
  run('renderAll()');
  const gh = dom.els.kpiRow.innerHTML.split('<div class="card">').find(c => c.includes('GH Security Total'));
  assert.match(gh, /vs 42d ago/);  // 9 Sep, the Python 30-day basis
  assert.doesNotMatch(gh, /Matches GitHub/);
  run("loadDate('20261007')");
  assert.match(dom.els.kpiRow.innerHTML, /no 30-day basis yet/);
});

test('secret scanning at zero is not an alarm, and says what it counts', () => {
  const zero = withTrend(); zero.run('renderAll()');
  const card = h => h.split('<div class="card">').find(c => c.includes('Secret Scanning'));
  assert.match(card(zero.dom.els.kpiRow.innerHTML), /kpi-val g">0<[\s\S]*default secret types; generic not collected/);
  assert.doesNotMatch(card(zero.dom.els.kpiRow.innerHTML), /P0|Rotate/);
  const some = load(FILES, { SNAPSHOTS: { '20261021': snapshot({ github: { secrets_total: 3 } }) }, DATES: ['20261021'], CURRENT_DATE: '20261021' });
  some.run('renderAll()');
  assert.match(card(some.dom.els.kpiRow.innerHTML), /kpi-val p0">3<[\s\S]*Rotate first/);
});

test('Zone A counts packages, and the zone cards say they cover the top 50 Inspector CVEs', () => {
  const { run, dom } = withTrend();
  run('renderAll(); renderDetail()');
  assert.match(dom.els.kpiRow.innerHTML, /Zone A Overlap[\s\S]*packages in both the images and the source/);
  const zones = dom.els.zoneRow.innerHTML;
  assert.equal((zones.match(/50 Inspector CVEs with the most findings/g) || []).length, 3);
  assert.doesNotMatch(zones, /Base image upgrade|closes most|Confirmed end-to-end/);
});

test('the combined ranking chart plots the weighted score, labelled with the weights in use', () => {
  const W = { insp_crit: 2, insp_high: 1, gh_crit: 7, gh_high: 3, code_scan: 4, secret: 9 };
  const s = snapshot();
  s.correlation.repo_ranking = [{ repo: 'a', insp_crit: 1, insp_high: 2, gh_crit: 1, gh_high: 1, code_scanning: 1, secrets: 1, combined_score: 0 }];
  const { run } = load(FILES, { SNAPSHOTS: { '20261021': s }, DATES: ['20261021'], CURRENT_DATE: '20261021', RANK_WEIGHTS: W });
  ChartStub.instances.length = 0;
  run('renderDetail()');
  const ds = ChartStub.instances.find(c => c.el.id === 'repoRankChart').config.data.datasets;
  assert.deepEqual(JSON.parse(JSON.stringify(ds.map(d => [d.label, d.data[0]]))),
                   [['Inspector (C×2 + H×1)', 4], ['Dependabot (C×7 + H×3)', 10], ['Code scanning ×4', 4], ['Secrets ×9', 9]]);
});

test('Trend compares the selected snapshot with the trend start, and marks it on the charts', () => {
  const { run, dom } = withTrend({ TREND_START: '20260701' });
  run("switchTab(document.getElementById('btn-trend'), 'trend')");
  const cards = dom.els.trendKpiRow.innerHTML;
  assert.match(cards, /since 2026-09-09/);           // the first snapshot from trend_start, not 12 May
  assert.doesNotMatch(cards, /Zone A CVEs|from baseline/);
  assert.match(cards, /Code Scanning/);
  assert.match(dom.els.trendMeta.textContent, /^2026-10-21 compared with 2026-09-09/);
  const annots = () => ChartStub.instances.filter(c => c.el.id === 'trendInspChart').at(-1)
    .config.options.plugins.annotation.annotations;
  assert.equal(annots().selected, undefined);       // the latest needs no marker
  run("loadDate('20261007')");                       // on the Trend tab: redrawn at once
  assert.match(dom.els.trendMeta.textContent, /^2026-10-07 compared with/);
  assert.equal(annots().selected.xMin, '2026-10-07');
});

test('without trend_start, Trend starts at the first snapshot', () => {
  const { run, dom } = withTrend();
  run("switchTab(document.getElementById('btn-trend'), 'trend')");
  assert.match(dom.els.trendMeta.textContent, /compared with 2026-05-12/);
});
