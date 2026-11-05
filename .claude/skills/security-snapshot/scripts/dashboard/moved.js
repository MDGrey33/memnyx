// Inlined into the dashboard page by build_dashboard.py, after the data constants
// (SNAPSHOTS, DATES, CURRENT_DATE, ORG, TREND_SERIES, ANNOTATIONS, MOVED, REGION,
// TREND_START).
// What moved tab. MOVED holds, per snapshot, the comparisons movement_page.py
// computed at build: against the previous snapshot and against the 30-day basis,
// each as a `view`. The fixed panels (verdict, waterfall, levers, repo movers)
// look the same every snapshot. "Why it moved" is the agent's note: blocks it
// chose for this snapshot (STYLEGUIDE.md), validated in Python and drawn here.
// Nothing here recalculates a number. Every text value passes through esc(); the
// note's lead and its prose and callout html were escaped by movement_page.py.

let movedBasis = null;  // basis picked on the tab; null means the previous snapshot

function movedEntries(date) {
  return (MOVED && MOVED[date]) || [];
}

function pickMoved(date, basis) {
  const entries = movedEntries(date);
  return entries.find(e => e.basis === basis) || entries[0] || null;
}

// ── Links ───────────────────────────────────────────────────────────────────
// An ECR repo maps to the GitHub repo with the same last path segment, the join
// correlation.py uses.
const mvRepoUrl  = r => `https://github.com/${encodeURIComponent(ORG)}/${encodeURIComponent(String(r).split('/').pop())}`;
const mvPrsUrl   = p => 'https://github.com/pulls?q=' + encodeURIComponent(`is:open is:pr org:${ORG} author:app/dependabot ${p}`);
const mvAlertUrl = p => `https://github.com/orgs/${encodeURIComponent(ORG)}/security/alerts/dependabot?q=` +
                        encodeURIComponent(`is:open package:${p}`);
// Copied from the console, not a documented link format. It carries no filter, so
// if AWS changes the route the worst case is the console's start page.
const mvInspectorUrl = () => REGION
  ? `https://${encodeURIComponent(REGION)}.console.aws.amazon.com/inspector/v2/home?region=${encodeURIComponent(REGION)}#/findings?by=repository`
  : 'https://console.aws.amazon.com/inspector/v2/home';

const MV_EXT = '<svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M9 2h5v5M14 2L7 9M12 9v4.5a.5.5 0 0 1-.5.5h-9a.5.5 0 0 1-.5-.5v-9a.5.5 0 0 1 .5-.5H7"/></svg>';
const MV_COPY = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="9" rx="1.5"/><path d="M10.5 3.5v-.5A1.5 1.5 0 0 0 9 1.5H3.5A1.5 1.5 0 0 0 2 3v6.5A1.5 1.5 0 0 0 3.5 11h.5"/></svg>';
const MV_TICK = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 8.5l3 3 7-7"/></svg>';

const mvLink = (text, url) =>
  `<a class="mv-lk" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(text)} ${MV_EXT}</a>`;
const mvCopy = name =>
  `<button class="mv-lk mv-icon" title="Copy name for the Inspector filter" aria-label="Copy ${esc(name)}"
     data-copy="${esc(name)}" onclick="copyMovedName(this)">${MV_COPY}</button>`;

function copyMovedName(btn) {
  if (!navigator.clipboard) return;
  navigator.clipboard.writeText(btn.dataset.copy).then(() => {
    btn.innerHTML = MV_TICK; btn.classList.add('done');
    setTimeout(() => { btn.innerHTML = MV_COPY; btn.classList.remove('done'); }, 1500);
  });
}

// ── Formatting ─────────────────────────────────────────────────────────────
const mvN = v => (v == null ? '–' : Number(v).toLocaleString('en-GB'));
const mvRatio = r => (r == null ? '' : '×' + Number(r).toFixed(2));  // the ratio comes from movement.py
const mvShort = s => slugToDate(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const mvTone = (a, b) => (b < a ? 'mv-good' : b > a ? 'mv-bad' : '');
// Tone colours, as in STYLEGUIDE.md. Series run oldest first: grey, then blue.
const MV_TONES = { fix: '#22c55e', inventory: '#94a3b8', gap: '#f59e0b', risk: '#ef4444', unknown: '#a78bfa', info: '#38bdf8' };
const MV_SERIES = ['#64748b', '#146bfa', '#f59e0b', '#a78bfa'];

// ── Components ─────────────────────────────────────────────────────────────

function mvVerdict(v) {
  if (!v) return '<div class="card mv-hero"><p class="mv-meta">Inspector critical + high is missing from one of the two snapshots.</p></div>';
  const tone = mvTone(v.prev, v.curr), arrow = v.delta < 0 ? '↓' : v.delta > 0 ? '↑' : '';
  const big = v.pct == null ? mvN(v.curr) : `${arrow} ${esc(Math.abs(v.pct))}%`;
  const f = v.factors;
  const factors = f ? `
    <div class="mv-factor"><div class="mv-k">Images with findings</div>
      <div class="mv-v">${mvN(f.images[0])} → ${mvN(f.images[1])}<small>${mvRatio(f.images_ratio)}</small></div></div>
    <div class="mv-factor"><div class="mv-k">Findings per image</div>
      <div class="mv-v ${mvTone(f.per_image[0], f.per_image[1])}">${mvN(f.per_image[0])} → ${mvN(f.per_image[1])}<small>${mvRatio(f.per_image_ratio)}</small></div></div>
    <div class="mv-hint">ECR images hold ${mvN(f.ecr[0])} → ${mvN(f.ecr[1])} of the total: images with findings × findings
      per image. The rest is EC2 and Lambda. Each factor moves for several reasons: fixes, retention, scanning coverage.</div>` : '';
  return `<div class="card mv-hero ${tone}">
    <div><div class="mv-eyebrow">${esc(v.label)}</div><div class="mv-big ${tone}">${big}</div>
      <div class="mv-from"><b>${mvN(v.prev)}</b> → <b>${mvN(v.curr)}</b> · ${v.delta ? `${mvN(Math.abs(v.delta))} ${v.delta < 0 ? 'fewer' : 'more'}` : 'no change'}
      ${v.critical ? `<br>critical alone ${mvN(v.critical.prev)} → ${mvN(v.critical.curr)}` : ''}</div></div>
    <div class="mv-factors">${factors}</div>
    <div class="mv-spark"><div class="mv-k" id="mvTrendHead">Trend</div>
      <div style="height:90px"><canvas id="mvTrend"></canvas></div><div class="mv-spark-cap" id="mvTrendCap"></div></div>
  </div>`;
}

function mvWarnings(ws) {
  if (!ws || !ws.length) return '';
  return `<div class="mv-warns">${ws.map(w => `<div class="mv-warn"><div class="mv-warn-i">!</div>
    <div><b>${esc(w.title)}</b><span>${esc(w.body)}</span></div></div>`).join('')}</div>`;
}

// The note's blocks, in the order the agent wrote them. Consecutive stats share a row.
function mvNote(note) {
  if (!note) return '<div class="card mv-gap-top"><p class="mv-meta">No "Why it moved" note written for this comparison yet.</p></div>';
  const out = [];
  let reason = 0;  // linked stats are numbered in the order written; their sections get the same number
  note.blocks.forEach((b, i) => {
    if (b.type === 'stat') {
      // A stat that names a section is a button to it; the target id was built in
      // Python from [a-z0-9-] only and is escaped here anyway.
      const tag = b.target ? 'button' : 'div';
      const go = b.target ? ` type="button" data-target="${esc(b.target)}" onclick="mvJump(this.dataset.target)" title="Go to the explanation"` : '';
      // A long value ("54,635 → 396") takes a smaller size so it stays on one line.
      const wide = String(b.value).length > 8 ? ' mv-stat-wide' : '';
      const body = `<div class="mv-stat-v">${esc(b.value)}</div><div class="mv-stat-l">${esc(b.label)}</div>` +
        (b.sub ? `<div class="mv-stat-s">${esc(b.sub)}</div>` : '');
      const stat = b.target
        ? `<${tag} class="mv-stat-block mv-tone-${esc(b.tone || 'none')} mv-stat-link${wide}"${go}>` +
          `<div class="mv-stat-idx">${++reason}</div><div class="mv-stat-body">${body}<div class="mv-stat-go">Why ↓</div></div></${tag}>`
        : `<${tag} class="mv-stat-block mv-tone-${esc(b.tone || 'none')}${wide}">${body}</${tag}>`;
      if (out.length && out[out.length - 1].stats) out[out.length - 1].stats.push(stat);
      else out.push({ stats: [stat] });
      return;
    }
    if (b.type === 'html') out.push(`<div class="mv-md">${b.html}</div>`);
    else if (b.type === 'bar' || b.type === 'line') {
      const rows = b.type === 'bar' ? b.rows.length : 0;
      out.push(`<div class="card mv-chart-block"><h4>${esc(b.title)}</h4>${b.unit ? `<div class="mv-sub">${esc(b.unit)}</div>` : ''}
        <div style="height:${b.type === 'bar' && rows > 6 ? Math.min(560, 40 + rows * 26) : 220}px"><canvas id="mvNote${i}"></canvas></div></div>`);
    } else if (b.type === 'callout') {
      out.push(`<div class="mv-callout mv-tone-${esc(b.tone)}"><b>${esc(b.title)}</b><div class="mv-md">${b.html}</div></div>`);
    } else if (b.type === 'error') {
      out.push(`<div class="mv-block-error">This block could not be shown: ${esc(b.message)}</div>`);
    }
  });
  return `<div class="mv-note">${out.map(o => (o.stats ? `<div class="mv-stats-row">${o.stats.join('')}</div>` : o)).join('')}</div>`;
}

function mvItem(it) {
  const acts = [];
  if (it.kind === 'repo') acts.push(mvLink('GitHub', mvRepoUrl(it.name)));
  if (it.dependabot) acts.push(mvLink('PRs', mvPrsUrl(it.name)), mvLink('Alerts', mvAlertUrl(it.name)));
  acts.push(mvLink('Inspector', mvInspectorUrl()));
  if (it.kind !== 'layer') acts.push(mvCopy(it.name));
  return `<div class="mv-item"><div><div class="mv-item-n">${it.kind === 'layer' ? `<code>${esc(it.name)}</code>` : esc(it.name)}</div>
    ${it.detail ? `<div class="mv-item-d">${esc(it.detail)}</div>` : ''}</div>
    <div class="mv-num">${mvN(it.ch)}</div><div class="mv-acts">${acts.join('')}</div></div>`;
}

function mvLevers(levers) {
  if (!levers) return '';
  return `<div class="mv-sec"><h2>What to fix next</h2>
    <p class="mv-sec-lede">Ranked by how many of today's critical + high each change removes. Some overlap: a package can sit in a listed base layer.</p>
    <div class="mv-levers">${levers.map((l, i) => {
      const items = l.items.map(mvItem);
      const width = Math.max(0, Math.min(100, Number(l.share) || 0));
      return `<div class="card mv-lever">
        <div class="mv-lever-head"><div class="mv-rank">${i + 1}</div><div><h3>${esc(l.title)}</h3><span class="mv-owner">${esc(l.owner)}</span></div></div>
        <div class="mv-impact"><div class="mv-pct">${esc(l.share)}%</div><div class="mv-bar"><i style="width:${width}%"></i></div>
          <div class="mv-abs">${mvN(l.removes)} critical + high</div></div>
        <div class="mv-how">${esc(l.how)}</div>
        <div class="mv-list">${items.slice(0, 4).join('')}</div>
        ${items.length > 4 ? `<details><summary>${items.length - 4} more</summary><div class="mv-list mv-list-more">${items.slice(4).join('')}</div></details>` : ''}
        ${l.more ? `<div class="mv-meta">and ${mvN(l.more)} more not shown</div>` : ''}
      </div>`;
    }).join('')}</div></div>`;
}

function mvRepoMovers(repos) {
  if (!repos || !repos.length) return '';
  return `<div class="mv-sec"><h2>Biggest moves by repo</h2>
    <p class="mv-sec-lede">Change in critical + high since this basis. Click a bar to open the repo on GitHub.</p>
    <div class="card"><div style="height:${Math.max(160, repos.length * 30)}px"><canvas id="mvRepos"></canvas></div></div></div>`;
}

function movedPanelHtml(date, basis) {
  const entries = movedEntries(date);
  if (!entries.length) {
    return '<div class="card"><p class="mv-meta">No comparison for ' + esc(fmtDate(date)) +
           ': it is the first snapshot, or its raw files are missing.</p></div>';
  }
  const e = pickMoved(date, basis);
  const buttons = entries.map(x =>
    `<button class="mv-basis${x === e ? ' active' : ''}" data-basis="${esc(x.basis)}"
       onclick="selectMovedBasis(this.dataset.basis)">${x.kind === 'previous' ? 'Previous snapshot' : '30 days'} · ${esc(fmtDate(x.basis))}</button>`
  ).join('');
  const where = esc(date + '/' + e.file);
  const rerun = `emit_movement.py --date ${esc(date)}`;
  const meta = e.detail === 'full'
    ? (e.on_disk ? `Generated from the snapshot files; also in ${where}.`
                 : `Generated from the snapshot files; ${where} is not written yet (${rerun} writes it).`)
    : (e.on_disk ? `Older comparison: the verdict, the waterfall and the note. ${where} holds the full detail as of when it was written.`
                 : `Older comparison: the verdict, the waterfall and the note. No movement file was written for it; ${rerun} writes one.`);
  const bar = `<div class="mv-bases">${buttons}<span class="mv-meta">${meta}</span></div>`;
  if (e.error) {
    return bar + `<div class="card"><p class="mv-meta">This comparison could not be computed (${esc(e.error)}).
                  See the build output.</p></div>`;
  }
  const v = e.view;
  return bar + mvVerdict(v.verdict) + mvWarnings(v.warnings) +
    `<div class="mv-sec"><h2>Why it moved</h2>
      <p class="mv-sec-lede">The chart is built from the data and looks the same every time. What follows it is written for this snapshot.</p>
      ${v.note && v.note.lead ? `<div class="mv-lead">${v.note.lead}</div>` : ''}
      ${v.waterfall ? `<div class="card mv-gap-top"><h4 class="mv-chart-title">Critical + high in ECR images, by what fixes them</h4>
        <div class="mv-sub">${mvN(v.waterfall.start)} → ${mvN(v.waterfall.end)}. EC2 and Lambda findings are not included.</div>
        <div style="height:240px"><canvas id="mvWaterfall"></canvas></div></div>` : ''}
      ${mvNote(v.note)}</div>` +
    mvLevers(v.levers) + mvRepoMovers(v.repos);
}

// ── Charts: built only while the tab is visible (a hidden canvas has no size) ──

function movedSeries(date) {
  return (TREND_SERIES || []).filter(s => (!TREND_START || s.date >= TREND_START) && s.date <= date);
}

function movedCharts(date, basis) {
  const e = pickMoved(date, basis);
  if (!e || e.error) return [];
  const v = e.view, grid = '#2a3649', tick = '#94a3b8', out = [];
  const series = movedSeries(date);
  if (v.verdict && series.length > 1) {
    const bases = new Set(movedEntries(date).map(x => x.basis));
    out.push({ id: 'mvTrend', config: {
      type: 'line',
      data: { labels: series.map(s => s.date), datasets: [{ data: series.map(s => s.insp_ch),
        borderColor: '#146bfa', borderWidth: 2, tension: .3, fill: false,
        pointRadius: series.map(s => s.date === date ? 4 : bases.has(s.date) ? 3 : 0),
        pointBackgroundColor: series.map(s => s.date === date ? '#22c55e' : '#94a3b8') }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false },
          tooltip: { callbacks: { title: c => fmtDate(c[0].label), label: c => mvN(c.raw) + ' critical + high' } } },
        scales: { x: { display: false }, y: { display: false, beginAtZero: true } } } } });
  }
  if (v.waterfall) {
    const W = v.waterfall; let run = W.start;
    const bars = [[0, W.start]], labels = [mvShort(e.basis)], colors = ['#64748b'];
    for (const s of W.steps) {
      bars.push([Math.min(run, run + s.delta), Math.max(run, run + s.delta)]);
      run += s.delta; labels.push(s.label); colors.push(s.delta < 0 ? '#22c55e' : '#ef4444');
    }
    bars.push([0, W.end]); labels.push(mvShort(date)); colors.push('#146bfa');
    out.push({ id: 'mvWaterfall', config: {
      type: 'bar', data: { labels, datasets: [{ data: bars, backgroundColor: colors, borderRadius: 3, maxBarThickness: 70 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false },
          tooltip: { callbacks: { label: c => { const i = c.dataIndex;
            if (i === 0 || i === bars.length - 1) return mvN(c.raw[1]);
            const d = W.steps[i - 1].delta; return (d > 0 ? '+' : '−') + mvN(Math.abs(d)); } } } },
        scales: { x: { ticks: { color: tick, font: { size: 11 } }, grid: { display: false } },
                  y: { ticks: { color: tick, callback: x => fmt(x) }, grid: { color: grid } } } } } });
  }
  ((v.note && v.note.blocks) || []).forEach((b, i) => {
    if (b.type !== 'bar' && b.type !== 'line') return;
    const pts = b.type === 'bar' ? b.rows : b.points;
    const single = b.series.length === 1;
    const colour = k => (single ? (MV_TONES[b.tone] || '#146bfa') : MV_SERIES[k % MV_SERIES.length]);
    out.push({ id: 'mvNote' + i, config: {
      type: b.type,
      data: { labels: pts.map(r => r[0]), datasets: b.series.map((name, k) => ({ label: name, data: pts.map(r => r[k + 1]),
        backgroundColor: colour(k), borderColor: colour(k), borderWidth: b.type === 'line' ? 2 : 0, borderRadius: 3,
        tension: .3, pointRadius: b.type === 'line' ? 2 : undefined })) },
      options: { maintainAspectRatio: false, indexAxis: b.type === 'bar' && pts.length > 6 ? 'y' : 'x',
        plugins: { legend: { display: !single, labels: { color: tick, boxWidth: 12 } },
          tooltip: { callbacks: { label: c => `${c.dataset.label}: ${mvN(c.raw)}` } } },
        scales: { x: { ticks: { color: tick, font: { size: 11 } }, grid: { color: grid } },
                  y: { ticks: { color: tick, font: { size: 11 } }, grid: { color: grid } } } } } });
  });
  if (v.repos && v.repos.length) {
    out.push({ id: 'mvRepos', config: {
      type: 'bar', data: { labels: v.repos.map(r => String(r.repo).split('/').pop()),
        datasets: [{ data: v.repos.map(r => r.delta), backgroundColor: v.repos.map(r => r.delta < 0 ? '#22c55e' : '#ef4444'), borderRadius: 3 }] },
      options: { indexAxis: 'y', maintainAspectRatio: false, plugins: { legend: { display: false } },
        onClick: (_e, els) => { if (els.length) window.open(mvRepoUrl(v.repos[els[0].index].repo), '_blank', 'noopener'); },
        scales: { x: { ticks: { color: tick, callback: x => (x < 0 ? '−' : '') + fmt(Math.abs(x)) }, grid: { color: grid } },
                  y: { ticks: { color: '#e2e8f0', font: { size: 11 } }, grid: { display: false } } } } } });
  }
  return out;
}

function movedTrendCaption(date) {
  const series = movedSeries(date);
  if (series.length < 2) return '';
  const val = s => s.insp_ch;
  const peak = series.reduce((a, b) => (val(b) > val(a) ? b : a));
  return `<span>${esc(mvShort(series[0].date))} <b>${mvN(val(series[0]))}</b></span>` +
         `<span>peak ${esc(mvShort(peak.date))} <b>${mvN(val(peak))}</b></span><span>now <b>${mvN(val(series.at(-1)))}</b></span>`;
}

function renderMoved() {
  const el = document.getElementById('movedPanel');
  if (!el) return;
  el.innerHTML = movedPanelHtml(activeDate, movedBasis);
  const cap = document.getElementById('mvTrendCap');
  if (cap) cap.innerHTML = movedTrendCaption(activeDate);
  const head = document.getElementById('mvTrendHead');
  const first = movedSeries(activeDate)[0];
  if (head) head.textContent = first ? 'Since ' + mvShort(first.date) : 'Trend';
  // Give each linked section the number and tone of the stat that points to it.
  const e = pickMoved(activeDate, movedBasis);
  movedReasons(e && e.view && e.view.note).forEach(({ target, index, tone }) => {
    const h = document.getElementById(target);
    if (!h) return;
    h.dataset.index = String(index);
    h.classList.add('mv-tone-' + (tone || 'none'));
  });
  const pane = document.getElementById('tab-moved');
  if (pane && pane.classList.contains('active')) {
    for (const c of movedCharts(activeDate, movedBasis)) mkChart(c.id, c.config);
  }
}

// The linked stats in order: [{target, index, tone}], numbered from 1 as drawn.
function movedReasons(note) {
  return ((note && note.blocks) || []).filter(b => b.type === 'stat' && b.target)
    .map((b, k) => ({ target: b.target, index: k + 1, tone: b.tone }));
}

// Scroll to a section of the note and highlight it briefly. No hash change: the
// URL belongs to the router (#moved/<date>/<basis>).
function mvJump(id) {
  const el = document.getElementById(id);
  if (!el) return;
  if (el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  el.classList.add('mv-flash');
  setTimeout(() => el.classList.remove('mv-flash'), 1600);
}

function selectMovedBasis(basis) {
  movedBasis = basis;
  renderMoved();
  urlWrite();
}
