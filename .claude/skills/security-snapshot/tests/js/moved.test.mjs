// The What moved tab, driven on both bases: the previous snapshot and the 30-day basis.
import test from 'node:test';
import assert from 'node:assert/strict';
import { load, snapshot, ChartStub } from './harness.mjs';

const FILES = ['core.js', 'app.js', 'moved.js'];

const view = (o = {}) => ({
  verdict: { label: 'Inspector critical + high', prev: 97555, curr: 24154, delta: -73401, pct: -75.2,
             critical: { prev: 15514, curr: 3878 }, factors: { images: [381, 216], per_image: [255.8, 111.4],
                                                                 images_ratio: 0.5, per_image_ratio: 0.436, ecr: [97474, 24054] } },
  warnings: [{ kind: 'inventory', title: '34% fewer images scanned (382 → 254)', body: 'Part of the fall is fewer images kept.' }],
  waterfall: { start: 97474, end: 24054, steps: [{ label: 'Kernel headers', delta: -47668 }, { label: 'OS packages', delta: -25752 }] },
  note: { lead: 'LEAD-TEXT', blocks: [
    { type: 'stat', value: '−54k', label: 'slim images', sub: '12 Oct', tone: 'fix' },
    { type: 'stat', value: '≈15k', label: 'retention', sub: null, tone: 'inventory' },
    { type: 'html', html: '<h3>Slim images</h3><p>CARD-BODY</p>' },
    { type: 'bar', title: 'The four slim repos', unit: 'critical + high', series: ['7 Oct', '21 Oct'], tone: null,
      rows: [['svc-01', 15234, 20], ['svc-02', 14280, 36]] },
    { type: 'stat', value: '33', label: 'out of scanning', sub: null, tone: 'gap' },
    { type: 'line', title: 'Dependabot critical', unit: null, series: ['Critical'], points: [['23 Sep', 41], ['21 Oct', 156]] },
    { type: 'callout', title: 'Coverage gap', tone: 'gap', html: '<p>CALLOUT-BODY</p>' },
    { type: 'error', message: "stat block: 'value' must be text" }] },
  levers: [
    { key: 'kernel_headers', title: 'Remove kernel headers', owner: 'Service team', how: 'Use slim.', removes: 9788, share: 40.5, more: 0,
      items: [{ kind: 'repo', name: 'ns-1/svc-03', ch: 3904, detail: 'Ubuntu 22.04' },
              { kind: 'repo', name: 'ns-1/a', ch: 3 }, { kind: 'repo', name: 'ns-1/b', ch: 2 },
              { kind: 'repo', name: 'ns-1/c', ch: 1 }, { kind: 'repo', name: 'ns-1/d', ch: 1 }] },
    { key: 'dependabot_dependencies', title: 'Merge Dependabot', owner: 'Service team', how: 'Merge.', removes: 7338, share: 30.4, more: 3,
      items: [{ kind: 'package', name: '@grpc/grpc-js', ch: 234, detail: 'node', dependabot: true }] },
    { key: 'base_layers', title: 'Refresh base', owner: 'Base image owner', how: 'Rebuild.', removes: 5162, share: 21.4, more: 0,
      items: [{ kind: 'layer', name: '24cced70ec2b', ch: 3020, detail: '121 images · 24 repos' }] }],
  repos: [{ repo: 'ns-1/svc-01', delta: -15214 }, { repo: 'ns-1/svc-04', delta: 40 }],
  ...o,
});
const headline = o => { const v = view(o); delete v.levers; delete v.repos; return v; };

const MOVED = {
  '20261021': [
    { basis: '20261007', kind: 'previous', file: 'movement.md', detail: 'full', on_disk: true, view: view() },
    { basis: '20260909', kind: '30-day', file: 'movement-vs-20260909.md', detail: 'full', on_disk: false,
      view: view({ verdict: { ...view().verdict, prev: 63426, delta: -39272, pct: -61.9 }, note: null }) },
  ],
  '20261007': [
    { basis: '20260923', kind: 'previous', file: 'movement.md', detail: 'headline', on_disk: true,
      view: headline({ verdict: { ...view().verdict, prev: 78449, curr: 97555, delta: 19106, pct: 24.4 },
                       waterfall: { start: 78449, end: 97555, steps: [{ label: 'Kernel headers', delta: 19106 }] } }) },
    { basis: '20260826', kind: '30-day', file: 'movement-vs-20260826.md', detail: 'headline', on_disk: false,
      view: headline({ note: null }) },
  ],
  '20260923': [
    { basis: '20260909', kind: 'previous', file: 'movement.md', detail: 'headline', error: 'KeyError' },
  ],
};
const DATES = ['20261021', '20261007', '20260923', '20260909', '20260826'];
const TREND = DATES.slice().reverse().map((d, i) => ({ date: d, insp_crit: 10 * (i + 1), insp_high: 100 * (i + 1), insp_ch: 120 * (i + 1) }));  // insp_ch is not the sum: the page must read it, not add
const page = (extra = {}) => load(FILES, {
  SNAPSHOTS: Object.fromEntries(DATES.map(d => [d, snapshot()])), DATES, CURRENT_DATE: '20261021', MOVED,
  TREND_SERIES: TREND, ORG: 'example-org', ...extra,
});
const html = (run, date = '20261021', basis = null) => run(`movedPanelHtml('${date}', ${basis ? `'${basis}'` : 'null'})`);

test('opens on the previous-snapshot comparison: verdict, factors, warnings, note and every section', () => {
  const { run } = page();
  const h = html(run);
  assert.match(h, /class="mv-basis active" data-basis="20261007"/);
  assert.match(h, /Previous snapshot · 2026-10-07/);
  assert.match(h, /30 days · 2026-09-09/);
  assert.match(h, /mv-big mv-good">↓ 75\.2%/);
  assert.match(h, /97,555<\/b> → <b>24,154<\/b> · 73,401 fewer/);
  assert.match(h, /critical alone 15,514 → 3,878/);
  assert.match(h, /Images with findings[\s\S]*381 → 216<small>×0\.50/);  // the payload's ratio, deliberately not 216 / 381
  assert.match(h, /mv-v mv-good">255\.8 → 111\.4/);  // fewer findings per image is the remediation
  assert.match(h, /34% fewer images scanned/);
  assert.match(h, /LEAD-TEXT[\s\S]*mvWaterfall[\s\S]*CARD-BODY/);  // the verdict sentence sits above the chart
  assert.match(h, /Critical \+ high by package, by what fixes them<\/h4>[\s\S]*97,474 → 24,054, all resource types\. A finding that names two packages counts in both/);
  assert.match(h, /Critical \+ high per image<\/div>/);
  assert.match(h, /ECR images hold 97,474 → 24,054 of the total: images with findings × critical \+ high\s+per image\. The rest is EC2 and Lambda\./);
  assert.match(h, /Ranked by today's critical \+ high naming the packages each change fixes\. Some overlap: a finding can name more than one package/);
  assert.doesNotMatch(h, /is the remediation|without fixing anything/);
  for (const s of ['Why it moved', 'What to fix next', 'Biggest moves by repo']) assert.match(h, new RegExp(`<h2>${s}</h2>`));
  assert.doesNotMatch(h, /<h2>(Where it moved|Checks|GitHub)<\/h2>/);
});

test('the 30-day basis shows its own verdict and says no note is written', () => {
  const { run } = page();
  const h = html(run, '20261021', '20260909');
  assert.match(h, /class="mv-basis active" data-basis="20260909"/);
  assert.match(h, /↓ 61\.9%/);
  assert.match(h, /No "Why it moved" note written for this comparison yet/);
  assert.match(h, /20261021\/movement-vs-20260909\.md is not written yet \(emit_movement\.py --date 20261021 writes it\)/);
});

test('a rise is red and says more', () => {
  const h = html(page().run, '20261007');
  assert.match(h, /mv-big mv-bad">↑ 24\.4%/);
  assert.match(h, /19,106 more/);
});

test('no movement says no change, not "0 more"', () => {
  const v = { ...view().verdict, prev: 500, curr: 500, delta: 0, pct: 0 };
  const h = html(page({ MOVED: { '20261021': [{ basis: '20261007', kind: 'previous', file: 'movement.md', detail: 'full',
    on_disk: true, view: view({ verdict: v }) }] } }).run);
  assert.match(h, /500<\/b> → <b>500<\/b> · no change/);
  assert.doesNotMatch(h, /0 more/);
});

test('the note draws its blocks in order; consecutive stats share a row', () => {
  const h = html(page().run);
  const note = h.slice(h.indexOf('class="mv-note"'));
  const order = ['−54k', '≈15k', 'CARD-BODY', 'mvNote3', '33', 'mvNote5', 'CALLOUT-BODY', 'could not be shown'].map(s => note.indexOf(s));
  assert.deepEqual(order, [...order].sort((a, b) => a - b));
  assert.ok(order.every(i => i >= 0));
  const rows = note.match(/<div class="mv-stats-row">/g);
  assert.equal(rows.length, 2);  // −54k and ≈15k together; 33 on its own after the bar
  assert.match(note, /mv-stats-row"><div class="mv-stat-block mv-tone-fix"><div class="mv-stat-v">−54k[\s\S]*12 Oct[\s\S]*mv-tone-inventory/);
  assert.match(note, /mv-callout mv-tone-gap"><b>Coverage gap<\/b><div class="mv-md"><p>CALLOUT-BODY/);
  assert.match(note, /mv-block-error">This block could not be shown: stat block: &#39;value&#39; must be text/);
  assert.match(note, /<h4>The four slim repos<\/h4><div class="mv-sub">critical \+ high/);
});

test('a linked stat is a button to its section; clicking it scrolls there and highlights it', () => {
  const v = view({ note: { lead: '', blocks: [
    { type: 'stat', value: '≈54k', label: 'slim', sub: null, tone: 'fix', target: 'mv-s-slim' },
    { type: 'stat', value: '2', label: 'plain', sub: null, tone: null },
    { type: 'html', html: '<h3 id="mv-s-slim">Slim</h3>' }] } });
  const { run, dom } = page({ MOVED: { '20261021': [{ basis: '20261007', kind: 'previous', file: 'f', detail: 'full', on_disk: true, view: v }] } });
  const h = html(run);
  assert.match(h, /<button class="mv-stat-block mv-tone-fix mv-stat-link" type="button" data-target="mv-s-slim" onclick="mvJump\(this\.dataset\.target\)"/);
  assert.match(h, /data-target="mv-s-slim"[^>]*><div class="mv-stat-idx">1<\/div><div class="mv-stat-body"><div class="mv-stat-v">≈54k/);
  assert.match(h, /Why ↓<\/div><\/div><\/button>/);
  assert.match(h, /<div class="mv-stat-block mv-tone-none"><div class="mv-stat-v">2/);  // no link: not a button
  assert.doesNotMatch(h, /mv-stat-wide"[^>]*><div class="mv-stat-v">≈54k/);  // short values keep the full size
  const heading = dom.byId('mv-s-slim');
  let scrolled = 0;
  heading.scrollIntoView = () => { scrolled += 1; };
  run("mvJump('mv-s-slim')");
  assert.equal(scrolled, 1);
  assert.equal(heading.classList.contains('mv-flash'), false);  // flashed, then cleared (setTimeout runs at once here)
  run("mvJump('mv-s-missing')");  // nothing to scroll to: no error
});

test('linked stats are numbered in order, and each section takes its number and tone', () => {
  const st = (value, target, tone) => ({ type: 'stat', value, label: 'l', sub: null, tone, target });
  const v = view({ note: { lead: '', blocks: [
    st('≈54k', 'mv-s-a', 'fix'), st('9', null, null), st('≈15k', 'mv-s-b', 'inventory'),
    { type: 'html', html: '<h3 id="mv-s-a">A</h3><h3 id="mv-s-b">B</h3>' }] } });
  const { run, dom } = page({ MOVED: { '20261021': [{ basis: '20261007', kind: 'previous', file: 'f', detail: 'full', on_disk: true, view: v }] } });
  const h = html(run);
  assert.deepEqual([...h.matchAll(/mv-stat-idx">(\d+)</g)].map(m => m[1]), ['1', '2']);  // the unlinked stat takes no number
  run('renderMoved()');
  assert.equal(dom.els['mv-s-a'].dataset.index, '1');
  assert.ok(dom.els['mv-s-a'].classList.contains('mv-tone-fix'));
  assert.equal(dom.els['mv-s-b'].dataset.index, '2');
  assert.ok(dom.els['mv-s-b'].classList.contains('mv-tone-inventory'));
});

test('a long stat value takes the smaller size so it stays on one line', () => {
  const v = view({ note: { lead: '', blocks: [{ type: 'stat', value: '54,635 → 396', label: 'x', sub: null, tone: 'fix' }] } });
  const { run } = page({ MOVED: { '20261021': [{ basis: '20261007', kind: 'previous', file: 'f', detail: 'full', on_disk: true, view: v }] } });
  assert.match(html(run), /mv-stat-block mv-tone-fix mv-stat-wide"><div class="mv-stat-v">54,635 → 396/);
});

test('a stat target is escaped where it reaches the markup', () => {
  const v = view({ note: { lead: '', blocks: [{ type: 'stat', value: '1', label: 'x', sub: null, tone: null, target: '"><zz>' }] } });
  const { run } = page({ MOVED: { '20261021': [{ basis: '20261007', kind: 'previous', file: 'f', detail: 'full', on_disk: true, view: v }] } });
  assert.doesNotMatch(html(run), /<zz/);
});

test('a stat without a tone still renders, in the neutral colour', () => {
  const v = view({ note: { lead: '', blocks: [{ type: 'stat', value: '1', label: 'x', sub: null, tone: null }] } });
  const { run } = page({ MOVED: { '20261021': [{ basis: '20261007', kind: 'previous', file: 'f', detail: 'full', on_disk: true, view: v }] } });
  assert.match(html(run), /mv-stat-block mv-tone-none/);
});

test('an older comparison has the verdict, waterfall and note only, and says where the rest is', () => {
  const { run } = page();
  const h = html(run, '20261007');
  assert.match(h, /mvWaterfall/);
  assert.match(h, /CARD-BODY/);
  assert.doesNotMatch(h, /What to fix next|Biggest moves by repo/);
  assert.match(h, /20261007\/movement\.md holds the full detail/);
  const missing = html(run, '20261007', '20260826');
  assert.match(missing, /No movement file was written for it; emit_movement\.py --date 20261007 writes one\./);
});

test('the newest comparison names its movement file when it exists', () => {
  assert.match(html(page().run), /also in 20261021\/movement\.md\./);
});

test('an unknown basis falls back to the previous snapshot', () => {
  assert.match(html(page().run, '20261021', '19990101'), /class="mv-basis active" data-basis="20261007"/);
});

test('a comparison that failed at build says so instead of an empty panel', () => {
  assert.match(html(page().run, '20260923'), /could not be computed \(KeyError\)/);
});

test('the first snapshot has no comparison', () => {
  assert.match(html(page().run, '20260826'), /No comparison for 2026-08-26/);
});

test('levers rank, show their share and give each item its actions', () => {
  const h = html(page().run);
  assert.match(h, /mv-rank">1<\/div><div><h3>Remove kernel headers/);
  assert.match(h, /mv-rank">2<\/div><div><h3>Merge Dependabot/);
  assert.match(h, /mv-pct">40\.5%<\/div><div class="mv-bar"><i style="width:40\.5%">/);
  const ocr = h.slice(h.indexOf('ns-1/svc-03'), h.indexOf('ns-1/svc-03') + 1500);
  assert.match(ocr, /href="https:\/\/github\.com\/example-org\/svc-03"/);  // ECR repo → GitHub repo by basename
  assert.match(ocr, /href="https:\/\/eu-west-2\.console\.aws\.amazon\.com\/inspector\/v2\/home\?region=eu-west-2#\/findings\?by=repository"/);
  assert.match(ocr, /data-copy="ns-1\/svc-03"/);
  assert.match(h, /<summary>1 more<\/summary>/);     // five items, four shown
  assert.match(h, /and 3 more not shown/);
  const grpc = h.slice(h.indexOf('@grpc/grpc-js'), h.indexOf('@grpc/grpc-js') + 1500);
  assert.match(grpc, /github\.com\/pulls\?q=is%3Aopen%20is%3Apr%20org%3Aexample-org%20author%3Aapp%2Fdependabot%20%40grpc%2Fgrpc-js/);
  assert.match(grpc, /github\.com\/orgs\/example-org\/security\/alerts\/dependabot\?q=is%3Aopen%20package%3A%40grpc%2Fgrpc-js/);
  const at = h.indexOf('24cced70ec2b'), layer = h.slice(at, h.indexOf('</div></div>', h.indexOf('mv-acts', at)));
  assert.match(layer, /Inspector/);
  assert.doesNotMatch(layer, /data-copy|GitHub/);   // a layer has no repo and no name to paste
});

test('the Inspector link falls back to the console start page without a region', () => {
  assert.match(html(page({ REGION: '' }).run), /href="https:\/\/console\.aws\.amazon\.com\/inspector\/v2\/home"/);
});

test('charts: trend from TREND_START, waterfall steps, repo movers coloured by direction', () => {
  const { run } = page({ TREND_START: '20260901' });  // between snapshots: the header must name the first point
  const charts = JSON.parse(run("JSON.stringify(movedCharts('20261021', null))"));
  assert.deepEqual(charts.map(c => c.id), ['mvTrend', 'mvWaterfall', 'mvNote3', 'mvNote5', 'mvRepos']);
  assert.deepEqual(charts[0].config.data.labels, ['20260909', '20260923', '20261007', '20261021']);
  const wf = charts[1].config.data;
  assert.deepEqual(wf.labels, ['7 Oct', 'Kernel headers', 'OS packages', '21 Oct']);
  assert.deepEqual(wf.datasets[0].data, [[0, 97474], [49806, 97474], [24054, 49806], [0, 24054]]);
  assert.deepEqual(charts[4].config.data.datasets[0].backgroundColor, ['#22c55e', '#ef4444']);
  assert.match(run("movedTrendCaption('20261021')"), /9 Sept <b>240<\/b>[\s\S]*peak 21 Oct <b>600<\/b>[\s\S]*now <b>600<\/b>/);
  assert.deepEqual(charts[0].config.data.datasets[0].data, [240, 360, 480, 600]);
  run('renderMoved()');
  assert.equal(run("document.getElementById('mvTrendHead').textContent"), 'Since 9 Sept');  // the first point, not the config date
});

test('the note\'s bar and line blocks become charts with their own series', () => {
  const charts = Object.fromEntries(JSON.parse(page().run("JSON.stringify(movedCharts('20261021', null))")).map(c => [c.id, c.config]));
  const bar = charts.mvNote3;
  assert.equal(bar.type, 'bar');
  assert.deepEqual(bar.data.labels, ['svc-01', 'svc-02']);
  assert.deepEqual(bar.data.datasets.map(d => [d.label, d.data, d.backgroundColor]),
                   [['7 Oct', [15234, 14280], '#64748b'], ['21 Oct', [20, 36], '#146bfa']]);  // oldest first: grey, then blue
  assert.equal(bar.options.plugins.legend.display, true);
  assert.equal(bar.options.indexAxis, 'x');
  const line = charts.mvNote5;
  assert.equal(line.type, 'line');
  assert.deepEqual(line.data.datasets[0].data, [41, 156]);
  assert.equal(line.options.plugins.legend.display, false);  // one series needs no legend
});

test('a single-series bar takes its tone colour, and many rows turn it on its side', () => {
  const rows = Array.from({ length: 8 }, (_, i) => ['r' + i, i]);
  const v = view({ note: { lead: '', blocks: [{ type: 'bar', title: 't', unit: null, series: ['n'], tone: 'risk', rows }] } });
  const { run } = page({ MOVED: { '20261021': [{ basis: '20261007', kind: 'previous', file: 'f', detail: 'full', on_disk: true, view: v }] } });
  const bar = JSON.parse(run("JSON.stringify(movedCharts('20261021', null))")).find(c => c.id === 'mvNote0').config;
  assert.equal(bar.data.datasets[0].backgroundColor, '#ef4444');
  assert.equal(bar.options.indexAxis, 'y');
});

test('a rising waterfall step is red and spans upward', () => {
  const { run } = page();
  const charts = JSON.parse(run("JSON.stringify(movedCharts('20261007', null))"));
  const wf = charts.find(c => c.id === 'mvWaterfall').config.data;
  assert.deepEqual(wf.datasets[0].data, [[0, 78449], [78449, 97555], [0, 97555]]);
  assert.equal(wf.datasets[0].backgroundColor[1], '#ef4444');
});

test('charts are drawn only while the tab is visible', () => {
  const { run, dom } = page();
  ChartStub.instances.length = 0;
  run('renderMoved()');
  assert.equal(ChartStub.instances.length, 0);
  assert.match(dom.els.movedPanel.innerHTML, /mv-hero/);
  run("switchTab(document.getElementById('btn-moved'), 'moved')");
  assert.deepEqual(ChartStub.instances.map(c => c.el.id), ['mvTrend', 'mvWaterfall', 'mvNote3', 'mvNote5', 'mvRepos']);
});

test('the copy button puts the name on the clipboard and shows a tick', () => {
  const { run, ctx } = page();
  run("const b = { dataset: { copy: 'ns-1/svc-03' }, classList: { add(){}, remove(){} }, innerHTML: '' }; copyMovedName(b); globalThis.__b = b");
  assert.deepEqual([...ctx.navigator.clipboard.copied], ['ns-1/svc-03']);
  assert.equal(run('__b.innerHTML'), run('MV_COPY'));  // the tick reverts (setTimeout runs at once in the stub)
});

test('picking a basis renders it and puts it in the URL', () => {
  const { run, dom } = page();
  run("switchTab(document.getElementById('btn-moved'), 'moved')");
  assert.match(dom.els.movedPanel.innerHTML, /↓ 75\.2%/);
  assert.equal(dom.history.replaced.at(-1), '#moved/20261021');
  run("selectMovedBasis('20260909')");
  assert.match(dom.els.movedPanel.innerHTML, /↓ 61\.9%/);
  assert.equal(dom.history.replaced.at(-1), '#moved/20261021/20260909');
});

test('a link to another snapshot and its basis opens that comparison', () => {
  const { run, dom } = page();
  run("applyHash('#moved/20261007/20260826')");
  assert.equal(run('activeDate'), '20261007');
  assert.equal(run('movedBasis'), '20260826');
  assert.match(dom.els.movedPanel.innerHTML, /class="mv-basis active" data-basis="20260826"/);
});

test('a link without a basis returns the tab to the previous-snapshot comparison', () => {
  const { run, dom } = page();
  run("applyHash('#moved/20261021/20260909')");
  run("applyHash('#moved/20261021')");
  assert.equal(run('movedBasis'), null);
  assert.match(dom.els.movedPanel.innerHTML, /↓ 75\.2%/);
});

test('a link to another tab leaves the picked basis alone', () => {
  const { run } = page();
  run("applyHash('#moved/20261021/20260909')");
  run("applyHash('#trend/20261021')");
  assert.equal(run('movedBasis'), '20260909');
});

test('changing snapshot resets the basis', () => {
  const { run } = page();
  run("applyHash('#moved/20261021/20260909')");
  run("loadDate('20261007')");
  assert.equal(run('movedBasis'), null);
});

test('parseHash accepts a basis only when that snapshot has it', () => {
  const { run } = page();
  assert.equal(run("JSON.stringify(parseHash('#moved/20261021/20260909'))"),
               JSON.stringify({ tab: 'moved', snap: '20261021', basis: '20260909' }));
  assert.equal(run("parseHash('#moved/20261007/20260909').basis"), null);
  assert.equal(run("parseHash('#moved/20991231/20260909').snap"), null);
});

test('the basis button passes its value from data-basis, never inside the onclick string', () => {
  const clicks = html(page().run).match(/onclick="selectMovedBasis[^"]*"/g);
  assert.equal(clicks.length, 2);
  for (const c of clicks) assert.equal(c, 'onclick="selectMovedBasis(this.dataset.basis)"');
});

test('every value from the data is escaped where it reaches the markup', () => {
  const X = '<zz onerror=1>';  // a tag the page never writes itself
  const bad = view({
    verdict: { ...view().verdict, label: X },
    warnings: [{ kind: 'outlier', title: X, body: X }],
    note: { lead: 'ok', blocks: [{ type: 'stat', value: X, label: X, sub: X, tone: X },
                                 { type: 'bar', title: X, unit: X, series: ['a'], tone: X, rows: [['a', 1]] },
                                 { type: 'line', title: X, unit: X, series: ['a'], points: [['a', 1], ['b', 2]] },
                                 { type: 'callout', title: X, tone: X, html: '' },
                                 { type: 'error', message: X }] },
    levers: [{ key: 'k', title: X, owner: X, how: X, removes: 1, share: X, more: 0,
               items: [{ kind: 'repo', name: X, ch: 1, detail: X }, { kind: 'package', name: X, ch: 1, dependabot: true }] }],
  });
  const { run } = load(FILES, {
    SNAPSHOTS: { '20261021': snapshot() }, DATES: ['20261021'], CURRENT_DATE: '20261021',
    MOVED: { '20261021': [{ basis: "x'><zz>", kind: '<zz>', file: '<zz>f', detail: 'full', on_disk: true, view: bad },
                          { basis: '2', kind: 'previous', file: 'f', detail: 'full', error: '<zz>E' }] },
  });
  const h = html(run) + html(run, '20261021', '2');
  assert.doesNotMatch(h, /<zz/);
  assert.equal((h.match(/&lt;zz/g) || []).length >= 24, true);  // every sink above, escaped
  assert.match(h, /data-basis="x&#39;&gt;&lt;zz&gt;"/);
  assert.match(h, /\(&lt;zz&gt;E\)/);
});
