// Inlined into the dashboard page by build_dashboard.py, after the data constants
// (SNAPSHOTS, DATES, CURRENT_DATE, ORG, TREND_SERIES, ANNOTATIONS, MOVED).
// Page logic: tabs, URL routing, date modal and the Breakdown and Trend tabs.

let D              = SNAPSHOTS[CURRENT_DATE];
const CHARTS       = {};

function mkChart(id, config) {
  CHARTS[id]?.destroy();
  CHARTS[id] = new Chart(document.getElementById(id), config);
}

function hBar(id, labels, datasets) {
  mkChart(id, {
    type:'bar', data:{labels, datasets},
    options:{
      responsive:true, maintainAspectRatio:false, indexAxis:'x',
      scales:{
        x:{stacked:true,grid:{display:false},ticks:{color:'#e2e8f0',font:{size:9},maxRotation:38,minRotation:38}},
        y:{stacked:true,grid:{color:'#334155'},ticks:{color:'#94a3b8',font:{size:9},callback:v=>v>=1000?(v/1000)+'K':v}},
      },
      plugins:{
        legend:{labels:{color:'#94a3b8',font:{size:10},boxWidth:10,padding:8}},
        tooltip:{...DARK,callbacks:{label:i=>` ${i.dataset.label}: ${fmtN(i.raw)}`}},
      }
    }
  });
}

// ── Tab switching ─────────────────────────────────────────────────────────────
// Chart.js measures the canvas container at creation time. Creating charts inside
// a display:none tab gives them a 0×0 canvas, and .resize() can't always recover.
// We defer chart rendering until the breakdown/trend tabs are actually visible.
let breakdownRendered = false;
let trendRendered     = false;
let currentTab        = 'moved';      // matches the default `.tab-pane.active` in HTML

function switchTab(btn, id, skipUrl) {
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+id).classList.add('active');
  btn.classList.add('active');
  currentTab = id;

  if (id === 'breakdown' && !breakdownRendered) {
    renderDetail();
    breakdownRendered = true;
  } else if (id === 'breakdown') {
    // Already rendered. requestAnimationFrame waits a frame for CSS to apply,
    // then forces a measure pass — handles browser-side container size changes.
    requestAnimationFrame(() => Object.values(CHARTS).forEach(c => c?.resize()));
  } else if (id === 'trend' && !trendRendered) {
    renderTrend();
    trendRendered = true;
  } else if (id === 'trend') {
    requestAnimationFrame(() => Object.values(CHARTS).forEach(c => c?.resize()));
  } else if (id === 'moved') {
    renderMoved();
  }

  if (!skipUrl) urlWrite();
}

// ── URL routing — shareable per-tab + per-snapshot links ──────────────────────
// Hash format: #<tab>/<snapshot>   e.g.  #breakdown/20260525
//              #moved/<snapshot>/<basis>  picks the comparison on the What moved tab
//              …/<section>  a section's share link (a slug, never eight digits, so it
//              cannot be read as a basis); followed once, then dropped by the next write
// On Apps Script, the dashboard runs inside Google's sandbox iframe — direct
// location.hash changes only affect the iframe URL, not the parent address bar.
// google.script.history.push / google.script.url.getLocation bridge to the
// parent URL. On local file:// we fall back to native location.hash.
const TAB_IDS = ['moved','breakdown','trend'];
const GAS = typeof google !== 'undefined' && google.script && google.script.url;

function switchTabById(id, skipUrl) {
  if (!TAB_IDS.includes(id)) return;
  const btn = document.querySelector('.tab-btn[data-tab="'+id+'"]');
  if (btn) switchTab(btn, id, skipUrl);
}

function parseHash(raw) {
  const clean = (raw || '').replace(/^#/, '');
  if (!clean) return { tab: null, snap: null, basis: null };
  const [t, s, ...rest] = clean.split('/');
  const snap = (s && SNAPSHOTS[s]) ? s : null;
  const b = rest.find(x => /^\d{8}$/.test(x));
  const p = rest.find(x => x && !/^\d{8}$/.test(x));
  return {
    tab:   TAB_IDS.includes(t)        ? t : null,
    snap,
    basis: (snap && b && movedEntries(snap).some(e => e.basis === b)) ? b : null,
    panel: slugPanel(p) || null,
  };
}

function viewHash() {
  return currentTab + '/' + activeDate + (currentTab === 'moved' && movedBasis ? '/' + movedBasis : '');
}

// The hash this page wrote last. Apps Script echoes a push back through the change
// handler; applying our own write again would redraw the tab and re-scroll. It is
// one-shot: consumed by its echo or by any navigation, so Back then Forward still
// lands on the page the address names.
let lastWritten = null;

function writeHash(h) {
  lastWritten = h;
  if (GAS && google.script.history) {
    google.script.history.push(null, null, h);
  } else if (location.hash !== '#'+h) {
    history.replaceState(null, '', '#'+h);
  }
}

function urlWrite() {
  writeHash(viewHash());
}

function applyHash(rawHash) {
  const clean = (rawHash || '').replace(/^#/, '');
  const echo = clean && clean === lastWritten;
  lastWritten = null;
  if (echo) return;
  const { tab, snap, basis, panel } = parseHash(clean);
  if (snap && snap !== activeDate) loadDate(snap, true);
  // On the What moved tab the link decides the basis, including none (the default).
  if (tab === 'moved' && basis !== movedBasis) { movedBasis = basis; renderMoved(); }
  if (tab) switchTabById(tab, true);
  if (tab && panel) scrollToPanel(panel);
}

// ── Section share links ───────────────────────────────────────────────────────
// Every section heading carries a 🔗 (panelLink in core.js; build_dashboard.py adds
// one to each card title). A click puts #<view>/<section> in the address bar and
// copies the full link. On Apps Script the page runs in Google's sandbox iframe and
// cannot read the parent address, so the link is built from PUBLISHED_URL, the
// /exec URL the build reads from clasp-projects.json.
// Jump, never glide: a smooth scroll started while the page is still drawing its
// charts stopped short (measured: 22px of ~2,900). The flash shows where you landed.
function scrollToPanel(raw) {
  const id = slugPanel(raw);
  const el = id && document.querySelector('[data-panel="' + id + '"]');
  if (!el) return;
  if (el.scrollIntoView) el.scrollIntoView({ block: 'start' });
  el.classList.add('panel-flash');
  setTimeout(() => el.classList.remove('panel-flash'), 1600);
}

function shareUrl(h) {
  if (GAS) return PUBLISHED_URL ? PUBLISHED_URL + '#' + h : null;
  return String(location.href || '').split('#')[0] + '#' + h;
}

// execCommand still copies inside a sandboxed iframe, where the Clipboard API can
// be blocked by the frame's permissions policy.
function legacyCopy(text) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-1000px';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch (e) {
    return false;
  }
}

function showToast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => t.classList.remove('show'), 2600);
}

function sharePanel(id) {
  const h = viewHash() + '/' + slugPanel(id);
  writeHash(h);
  scrollToPanel(id);
  const url = shareUrl(h);
  const fallback = () => showToast(url && legacyCopy(url) ? 'Link copied' : 'Copy the link from the address bar');
  if (!url) return fallback();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(() => showToast('Link copied'), fallback);
  } else {
    fallback();
  }
}

window.addEventListener('DOMContentLoaded', () => {
  if (GAS) {
    google.script.url.getLocation(loc => applyHash((loc && loc.hash) || ''));
  } else {
    applyHash(location.hash || '');
  }
});

if (typeof google !== 'undefined' && google.script && google.script.history) {
  google.script.history.setChangeHandler(e => {
    applyHash((e && e.location && e.location.hash) || '');
  });
} else {
  window.addEventListener('hashchange', () => applyHash(location.hash || ''));
}

// ── Date modal ────────────────────────────────────────────────────────────────
function fmtDate(s){return s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8)}

let activeDate    = CURRENT_DATE;   // currently loaded snapshot
let selectedDate  = CURRENT_DATE;   // selection inside the modal (not yet committed)

function updateSnapDisplay() {
  document.getElementById('snapDisplay').textContent = fmtDate(activeDate);
}

function openDateModal() {
  selectedDate = activeDate;        // pre-select the current snapshot
  const body   = document.getElementById('dateModalBody');
  const footer = document.getElementById('dateModalFooter');

  if (DATES.length === 1) {
    body.innerHTML = `
      <div class="snap-notice">
        Only one snapshot is available.<br>
        <b>${fmtDate(DATES[0])}</b> — currently loaded.
      </div>`;
    footer.innerHTML = `
      <button class="btn btn-ghost" onclick="closeDateModal()">Close</button>`;
  } else {
    // The snapshot the loaded one is compared with over 30 days (its What moved
    // basis), and the snapshots whose comparison has a written note.
    const longBasis = (movedEntries(activeDate).find(e => e.kind === '30-day') || {}).basis;
    const hasNote = d => movedEntries(d).some(e => e.view && e.view.note);
    body.innerHTML = `<div class="date-list" id="dateList">` +
      DATES.map((d, i) => {
        const tags = [
          i === 0            ? `<span class="dtag dtag-latest">Latest</span>` : '',
          d === activeDate   ? `<span class="dtag dtag-current">Current</span>` : '',
          d === longBasis    ? `<span class="dtag dtag-basis" title="What moved compares the current snapshot with this one over 30 days">30-day basis</span>` : '',
          hasNote(d)         ? `<span class="dtag dtag-note" title="Has a written Why it moved note">Note</span>` : '',
        ].join('');
        return `<div class="date-list-item${d===selectedDate?' selected':''}"
                     data-date="${d}" onclick="selectModalDate('${d}')">
                  <span class="date-list-date">${fmtDate(d)}</span>
                  <span class="date-list-tags">${tags}</span>
                </div>`;
      }).join('') + `</div>`;

    footer.innerHTML = `
      <button class="btn btn-ghost" onclick="closeDateModal()">Cancel</button>
      <button class="btn btn-primary" id="loadSnapBtn"
              onclick="confirmLoadDate()"
              ${selectedDate === activeDate ? 'disabled' : ''}>
        Load Snapshot
      </button>`;
  }

  document.getElementById('dateModal').classList.add('open');
  document.addEventListener('keydown', handleModalKeydown);
}

function selectModalDate(date) {
  selectedDate = date;
  document.querySelectorAll('#dateList .date-list-item').forEach(el => {
    el.classList.toggle('selected', el.dataset.date === date);
  });
  const btn = document.getElementById('loadSnapBtn');
  if (btn) btn.disabled = (date === activeDate);
}

function confirmLoadDate() {
  if (!selectedDate || selectedDate === activeDate) return;
  loadDate(selectedDate);
  closeDateModal();
}

function closeDateModal() {
  document.getElementById('dateModal').classList.remove('open');
  document.removeEventListener('keydown', handleModalKeydown);
}

function handleOverlayClick(e) {
  if (e.target === document.getElementById('dateModal')) closeDateModal();
}

function handleModalKeydown(e) {
  if (e.key === 'Escape') closeDateModal();
}

function loadDate(date, skipUrl) {
  D          = SNAPSHOTS[date];
  activeDate = date;
  movedBasis = null;  // each snapshot opens on its own previous-snapshot comparison
  updateSnapDisplay();
  renderAll();
  // Trend marks the selected snapshot: redraw it now if visible, else on next open.
  if (currentTab === 'trend') renderTrend(); else trendRendered = false;
  if (!skipUrl) urlWrite();
}

// ── Main render — always-visible content only (banners, KPIs, What moved) ──
// Detail-tab content (zones, convergence table, all charts) is deferred to
// renderDetail() to avoid the hidden-canvas issue.
function renderAll() {
  const insp = D.inspector, gh = D.github, corr = D.correlation;
  const rawTotal = insp.critical + insp.high + insp.medium;

  // -- Banners
  document.getElementById('secretsBanner').innerHTML = gh.secrets_total > 0
    ? `<div class="banner-p0"><div class="icon">⚠</div><div>
         <div class="title">P0 — ${gh.secrets_total} open secret scanning alerts</div>
         <div class="sub">Exposed credentials committed to source code. Triage and rotate before all other work.</div>
       </div></div>`
    : '';

  // -- What moved
  renderMoved();

  // -- KPIs
  const ghTotal = (typeof gh.security_total === 'number')
    ? gh.security_total
    : (gh.vuln_total + gh.code_total + gh.secrets_total);
  // The 30-day basis is the one movement_page.py chose (What moved and the date
  // picker use the same), so every 30-day figure on the page names the same snapshot.
  const longBasis = (movedEntries(activeDate).find(e => e.kind === '30-day') || {}).basis;
  const basisRow = longBasis && TREND_SERIES.find(s => s.date === longBasis);
  const ghTotalSub = basisRow
    ? deltaSub(ghTotal, basisRow.gh_total, Math.round((slugToDate(activeDate) - slugToDate(longBasis)) / 86400e3))
    : 'no 30-day basis yet';

  document.getElementById('kpiRow').innerHTML = [
    ['Inspector Raw',     fmt(rawTotal),          'c',  `${fmtN(insp.unique_cves)} unique CVEs · ~${insp.fanout}× fan-out`],
    ['GH Security Total', fmtN(ghTotal),          'b',  ghTotalSub],
    ['Dependabot Alerts', fmtN(gh.vuln_total),    'h',  `${fmtN(gh.vuln_critical)} CRIT · ${fmtN(gh.vuln_high)} HIGH`],
    ['Code Scanning',     fmtN(gh.code_total),    'b',  `${fmtN(gh.code_errors)} errors · ${gh.code_total-gh.code_errors} warnings`],
    ['Secret Scanning',   fmtN(gh.secrets_total), gh.secrets_total > 0 ? 'p0' : 'g', (gh.secrets_total > 0 ? 'Rotate first · ' : '') + 'default secret types; generic not collected'],
    ['Zone A Overlap',    fmtN(corr.zone_a_pkgs), 'g',  'packages in both the images and the source'],
  ].map(([l,v,c,s])=>
    `<div class="card"><div class="kpi-label">${l}</div>
     <div class="kpi-val ${c}">${v}</div>
     <div class="kpi-sub">${s}</div></div>`
  ).join('');


  // -- Breakdown tab content: render only when visible (What moved is the
  //    default tab, so on first load this waits for the Breakdown click).
  if (breakdownRendered) {
    // Breakdown was previously opened; refresh its content for the new D.
    renderDetail();
  } else if (document.getElementById('tab-breakdown').classList.contains('active')) {
    renderDetail();
    breakdownRendered = true;
  }
}

// ── Detail tab — zones, convergence table, all charts ─────────────────────────
// Called when the detail tab first becomes visible (or on date change if it was
// already initialised). All canvas-using charts MUST be created here, never in
// renderAll(), to avoid the 0×0-canvas-in-hidden-tab issue.
function renderDetail() {
  const insp = D.inspector, gh = D.github, corr = D.correlation;

  // -- Zones
  document.getElementById('zoneRow').innerHTML = [
    // CVE zones compare Inspector's 50 CVEs with the most findings against every
    // Dependabot alert (correlation.py); the cards say so rather than imply all CVEs.
    ['Zone A',corr.zone_a_cves,'#22c55e','CVEs in both sources',      'Of the 50 Inspector CVEs with the most findings: also flagged by Dependabot.'],
    ['Zone B',corr.zone_b,     '#146bfa','Inspector only',            'Of the 50 Inspector CVEs with the most findings: not flagged by Dependabot.'],
    ['Zone C',corr.zone_c,     '#f97316','GitHub only',               'Flagged by Dependabot, not among the 50 Inspector CVEs with the most findings.'],
  ].map(([l,v,c,s,d])=>
    `<div class="card zone-card">
       <div class="zone-lbl">${l}</div>
       <div class="zone-val" style="color:${c}">${fmtN(v)}</div>
       <div style="font-size:12px;font-weight:600;color:var(--text)">${s}</div>
       <div class="zone-desc">${d}</div>
     </div>`
  ).join('');

  // -- Convergence table
  const SB = {
    Inspector: '<span class="signal-badge s-insp">Inspector</span>',
    Dependabot:'<span class="signal-badge s-dep">Dependabot</span>',
    CodeScan:  '<span class="signal-badge s-cs">CodeScan</span>',
    Secrets:   '<span class="signal-badge s-sec">Secrets</span>',
  };
  document.getElementById('convergenceTbody').innerHTML = (corr.convergence||[]).map(r=>{
    const badges = (r.signals||[]).map(s=>SB[s]||esc(s)).join('');
    // GAS parser bug: a template literal containing }/${ (close-interp, slash, open-interp)
    // is misread as the start of a regex, mangling the rest of the script and producing
    // "Unexpected token '<'" in the served page. Use string concatenation for any URL or
    // path built from multiple variables. Plain template literals without ${...}/${...}
    // (e.g., outer HTML strings with </td>) are fine.
    const url    = 'https://github.com/' + encodeURIComponent(ORG) + '/' + encodeURIComponent(r.repo) + '/security/dependabot';
    return `<tr>
      <td><a class="repo-link" href="${esc(url)}" target="_blank">${esc(r.repo)}</a></td>
      <td>${badges}</td>
      <td>${fmtN(r.insp_crit+r.insp_high)}</td>
      <td>${fmtN(r.gh_crit+r.gh_high)}</td>
      <td>${fmtN(r.code_scanning)}</td>
      <td>${r.secrets>0?`<b style="color:var(--crit)">${fmtN(r.secrets)}</b>`:'0'}</td>
      <td style="color:var(--muted);font-size:11px">${fmtN(r.combined_score)}</td>
    </tr>`;
  }).join('');

  // -- Repo ranking chart
  const rr = corr.repo_ranking;
  // Bars are the weighted parts of combined_score, so their length is the order.
  // The weights come from correlation.py through RANK_WEIGHTS, never a copy here.
  const W = RANK_WEIGHTS;
  hBar('repoRankChart', rr.map(r=>r.repo), [
    {label:`Inspector (C×${W.insp_crit} + H×${W.insp_high})`, data:rr.map(r=>r.insp_crit*W.insp_crit+r.insp_high*W.insp_high), backgroundColor:'#146bfa88',borderColor:'#146bfa',borderWidth:1,stack:'s'},
    {label:`Dependabot (C×${W.gh_crit} + H×${W.gh_high})`,     data:rr.map(r=>r.gh_crit*W.gh_crit+r.gh_high*W.gh_high),         backgroundColor:'#22c55e88',borderColor:'#22c55e',borderWidth:1,stack:'s'},
    {label:`Code scanning ×${W.code_scan}`,                    data:rr.map(r=>r.code_scanning*W.code_scan),                       backgroundColor:'#eab30888',borderColor:'#eab308',borderWidth:1,stack:'s'},
    {label:`Secrets ×${W.secret}`,                             data:rr.map(r=>r.secrets*W.secret),                                backgroundColor:'#ef444488',borderColor:'#ef4444',borderWidth:1,stack:'s'},
  ]);

  // -- Secret types doughnut
  {
    const items = gh.secrets_by_type.slice(0,10);
    mkChart('secretTypeChart', {
      type:'doughnut',
      data:{
        labels: items.map(x=>x.type.replace(/_/g,' ').replace('aws ','AWS ').replace('google ','Google ').replace('github ','GitHub ')),
        datasets:[{
          data: items.map(x=>x.count),
          backgroundColor:['#ef4444cc','#f97316cc','#eab308cc','#22c55ecc','#3b82f6cc','#a855f7cc','#ec4899cc','#14b8a6cc','#6366f1cc','#f43f5ecc'],
          borderWidth:1, hoverOffset:4,
        }]
      },
      options:{responsive:true,maintainAspectRatio:false,cutout:'55%',
        plugins:{legend:{position:'right',labels:{color:'#94a3b8',font:{size:9},boxWidth:8,padding:5}},
                 tooltip:{...DARK,callbacks:{label:i=>` ${i.label}: ${i.raw}`}}}}
    });
  }

  // -- Code scanning bar
  {
    const items = gh.cs_by_repo.slice(0,10);
    hBar('csRepoChart', items.map(x=>x.repo),
      [{label:'Alerts',data:items.map(x=>x.count),backgroundColor:'#eab30888',borderColor:'#eab308',borderWidth:1,borderRadius:3}]
    );
  }

  // -- Inspector repo/pkg charts
  hBar('inspRepoChart', insp.top_repos.map(r=>r.name), [
    {label:'Critical',data:insp.top_repos.map(r=>r.c),backgroundColor:'#ef444488',borderColor:'#ef4444',borderWidth:1,stack:'s'},
    {label:'High',    data:insp.top_repos.map(r=>r.h),backgroundColor:'#f9731688',borderColor:'#f97316',borderWidth:1,stack:'s'},
    {label:'Medium',  data:insp.top_repos.map(r=>r.m),backgroundColor:'#eab30888',borderColor:'#eab308',borderWidth:1,stack:'s'},
  ]);
  hBar('inspPkgChart', insp.top_pkgs.map(p=>p.name), [
    {label:'Critical',data:insp.top_pkgs.map(p=>p.c),backgroundColor:'#ef444488',borderColor:'#ef4444',borderWidth:1,stack:'s'},
    {label:'High',    data:insp.top_pkgs.map(p=>p.h),backgroundColor:'#f9731688',borderColor:'#f97316',borderWidth:1,stack:'s'},
  ]);

  // -- GitHub repo/pkg charts
  const gr = gh.top_repos.slice(0,12);
  hBar('ghRepoChart', gr.map(r=>r.repo), [
    {label:'Critical', data:gr.map(r=>r.CRITICAL||0), backgroundColor:'#ef444488',borderColor:'#ef4444',borderWidth:1,stack:'s'},
    {label:'High',     data:gr.map(r=>r.HIGH||0),     backgroundColor:'#f9731688',borderColor:'#f97316',borderWidth:1,stack:'s'},
    {label:'Moderate', data:gr.map(r=>r.MODERATE||0), backgroundColor:'#eab30888',borderColor:'#eab308',borderWidth:1,stack:'s'},
  ]);
  const gp = gh.top_pkgs.slice(0,15);
  hBar('ghPkgChart', gp.map(p=>p.package), [
    {label:'Critical', data:gp.map(p=>p.critical), backgroundColor:'#ef444488',borderColor:'#ef4444',borderWidth:1,stack:'s'},
    {label:'High',     data:gp.map(p=>p.high),     backgroundColor:'#f9731688',borderColor:'#f97316',borderWidth:1,stack:'s'},
    {label:'Moderate', data:gp.map(p=>p.moderate), backgroundColor:'#eab30888',borderColor:'#eab308',borderWidth:1,stack:'s'},
  ]);

}

// ── Trend tab ─────────────────────────────────────────────────────────────────
// Reads TREND_SERIES (all snapshots compiled at build time) and ANNOTATIONS
// (static event markers). Independent of the selected snapshot — always shows
// the full history.
function renderTrend() {
  if (!TREND_SERIES || TREND_SERIES.length === 0) {
    document.getElementById('trendKpiRow').innerHTML =
      '<div class="card" style="grid-column:1/-1;text-align:center">' +
      '<div class="kpi-label">No snapshots available</div></div>';
    return;
  }

  // The cards compare the selected snapshot with the first one from trend_start
  // (config) on; the charts keep every snapshot and mark the selected one.
  const startAt = TREND_SERIES.findIndex(s => !TREND_START || s.date >= TREND_START);
  const base    = TREND_SERIES[Math.max(0, startAt)];
  const current = TREND_SERIES.find(s => s.date === activeDate) || TREND_SERIES[TREND_SERIES.length - 1];
  const labels  = TREND_SERIES.map(s => fmtDate(s.date));
  const nSnaps  = TREND_SERIES.length;

  document.getElementById('trendMeta').textContent =
    fmtDate(current.date) + ' compared with ' + fmtDate(base.date) + '  ·  ' + nSnaps + ' snapshot' + (nSnaps > 1 ? 's' : '') +
    ' in the charts  ·  All metrics: lower = better';

  // Stat cards — selected snapshot against the trend start; lower is always better
  document.getElementById('trendKpiRow').innerHTML = [
    ['Inspector Critical', current.insp_crit,   base.insp_crit,   'c'],
    ['Inspector High',     current.insp_high,   base.insp_high,   'h'],
    ['Unique CVEs',        current.unique_cves, base.unique_cves, 'b'],
    ['GH Security Total',  current.gh_total,    base.gh_total,    'b'],
    ['Dependabot',         current.gh_vuln,     base.gh_vuln,     'h'],
    ['Code Scanning',      current.gh_code,     base.gh_code,     'b'],
  ].map(([lbl, cur, bas, cls]) => {
    const d   = cur - bas;
    const pct = bas > 0 ? (Math.abs(d) / bas * 100).toFixed(1) : '0.0';
    const dir = d > 0 ? '↑' : d < 0 ? '↓' : '→';
    const dc  = d > 0 ? 'var(--crit)' : d < 0 ? 'var(--low)' : 'var(--muted)';
    return `<div class="card">
      <div class="kpi-label">${lbl}</div>
      <div class="kpi-val ${cls}">${fmtN(cur)}</div>
      <div class="kpi-sub" style="color:${dc}">${dir} ${fmtN(Math.abs(d))} (${pct}%) since ${fmtDate(base.date)}</div>
    </div>`;
  }).join('');

  // Annotation vertical lines — shared across both charts
  const annots = {};
  if (current !== TREND_SERIES[TREND_SERIES.length - 1]) {
    annots.selected = {
      type: 'line', xMin: fmtDate(current.date), xMax: fmtDate(current.date),
      borderColor: '#146bfa', borderWidth: 2,
      label: { display: true, content: 'Selected', color: '#e2e8f0', backgroundColor: '#146bfa', font: { size: 9 }, position: 'end' },
    };
  }
  (ANNOTATIONS || []).forEach(a => {
    const lbl = fmtDate(a.date);
    if (!labels.includes(lbl)) return;
    annots['a' + a.date] = {
      type: 'line', xMin: lbl, xMax: lbl,
      borderColor: '#94a3b866', borderWidth: 1, borderDash: [4, 4],
      label: {
        display: true, content: a.label,
        color: '#94a3b8', backgroundColor: '#1e293b',
        font: { size: 9 }, position: 'start',
      },
    };
  });

  // Inspector chart: stacked bars (C + H) with Unique CVEs line on right axis
  CHARTS['trendInsp']?.destroy();
  CHARTS['trendInsp'] = new Chart(document.getElementById('trendInspChart'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          type: 'bar', label: 'Critical',
          data: TREND_SERIES.map(s => s.insp_crit),
          backgroundColor: '#ef444488', borderColor: '#ef4444', borderWidth: 1,
          stack: 's', yAxisID: 'yL',
        },
        {
          type: 'bar', label: 'High',
          data: TREND_SERIES.map(s => s.insp_high),
          backgroundColor: '#f9731688', borderColor: '#f97316', borderWidth: 1,
          stack: 's', yAxisID: 'yL',
        },
        {
          type: 'line', label: 'Unique CVEs',
          data: TREND_SERIES.map(s => s.unique_cves),
          borderColor: '#146bfa', backgroundColor: '#146bfa22',
          borderWidth: 2, pointRadius: 5, pointBackgroundColor: '#146bfa',
          tension: 0, yAxisID: 'yR',
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x:  { grid: { color: '#334155' }, ticks: { color: '#e2e8f0', font: { size: 11 } } },
        yL: {
          type: 'linear', position: 'left', stacked: true,
          grid: { color: '#334155' },
          ticks: { color: '#94a3b8', font: { size: 10 },
                   callback: v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'K' : v },
          title: { display: true, text: 'Findings (C+H)', color: '#94a3b8', font: { size: 11 } },
        },
        yR: {
          type: 'linear', position: 'right',
          grid: { display: false },
          ticks: { color: '#146bfa', font: { size: 10 },
                   callback: v => v >= 1e3 ? (v/1e3).toFixed(0)+'K' : v },
          title: { display: true, text: 'Unique CVEs', color: '#146bfa', font: { size: 11 } },
        },
      },
      plugins: {
        legend:     { labels: { color: '#94a3b8', font: { size: 11 }, boxWidth: 12, padding: 10 } },
        tooltip:    { ...DARK, callbacks: { label: i => ' ' + i.dataset.label + ': ' + fmtN(i.raw) } },
        annotation: { annotations: annots },
      },
    },
  });

  // GitHub Source chart: Total + three source breakdowns on one linear axis.
  const ghTotalSeries = TREND_SERIES.map(s =>
    (typeof s.gh_total === 'number') ? s.gh_total : (s.gh_vuln + s.gh_code + s.gh_secrets)
  );
  CHARTS['trendGh']?.destroy();
  CHARTS['trendGh'] = new Chart(document.getElementById('trendGhChart'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Total (GitHub Overview)', data: ghTotalSeries,
          borderColor: '#146bfa', backgroundColor: '#146bfa22',
          borderWidth: 3, pointRadius: 5, tension: 0 },
        { label: 'Dependabot Vulns', data: TREND_SERIES.map(s => s.gh_vuln),
          borderColor: '#f97316', backgroundColor: '#f9731622',
          borderWidth: 2, pointRadius: 4, tension: 0 },
        { label: 'Code Scanning',    data: TREND_SERIES.map(s => s.gh_code),
          borderColor: '#eab308', backgroundColor: '#eab30822',
          borderWidth: 2, pointRadius: 4, tension: 0 },
        { label: 'Secret Scanning',  data: TREND_SERIES.map(s => s.gh_secrets),
          borderColor: '#ef4444', backgroundColor: '#ef444422',
          borderWidth: 2, pointRadius: 4, tension: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { grid: { color: '#334155' }, ticks: { color: '#e2e8f0', font: { size: 11 } } },
        y: {
          // Linear, not logarithmic: these series are expected to reach 0
          // (that's the success state) and Chart.js log axes cannot plot 0.
          type: 'linear',
          beginAtZero: true,
          grid: { color: '#334155' },
          ticks: { color: '#94a3b8', font: { size: 10 },
                   callback: v => v >= 1e3 ? (v/1e3).toFixed(0)+'K' : v },
          title: { display: true, text: 'Open Alerts', color: '#94a3b8', font: { size: 11 } },
        },
      },
      plugins: {
        legend:     { labels: { color: '#94a3b8', font: { size: 11 }, boxWidth: 12, padding: 10 } },
        tooltip:    { ...DARK, callbacks: { label: i => ' ' + i.dataset.label + ': ' + fmtN(i.raw) } },
        annotation: { annotations: annots },
      },
    },
  });

  // GitHub Severity chart: open alerts over time by severity, across all three sources.
  // Total + Critical/High/Medium/Low computed across all three sources.
  renderGhSeverityChart(labels, annots);
}

// Render the GitHub Severity trend chart. Severity counts are computed across
// all three sources (Dependabot + Code Scanning + default secret alerts) on one linear axis.
function renderGhSeverityChart(labels, annots) {
  const totalSeries = TREND_SERIES.map(s =>
    (typeof s.gh_total === 'number') ? s.gh_total : (s.gh_vuln + s.gh_code + s.gh_secrets)
  );
  const critSeries = TREND_SERIES.map(s => s.gh_sev_critical);
  const highSeries = TREND_SERIES.map(s => s.gh_sev_high);
  const medSeries  = TREND_SERIES.map(s => s.gh_sev_medium);
  const lowSeries  = TREND_SERIES.map(s => s.gh_sev_low);

  CHARTS['trendGhSev']?.destroy();
  CHARTS['trendGhSev'] = new Chart(document.getElementById('trendGhSevChart'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Total (GitHub Overview)', data: totalSeries,
          borderColor: '#146bfa', backgroundColor: '#146bfa22',
          borderWidth: 3, pointRadius: 5, tension: 0 },
        { label: 'Critical', data: critSeries,
          borderColor: '#ec4899', backgroundColor: '#ec489922',
          borderWidth: 2, pointRadius: 4, tension: 0 },
        { label: 'High',     data: highSeries,
          borderColor: '#f97316', backgroundColor: '#f9731622',
          borderWidth: 2, pointRadius: 4, tension: 0 },
        { label: 'Medium',   data: medSeries,
          borderColor: '#eab308', backgroundColor: '#eab30822',
          borderWidth: 2, pointRadius: 4, tension: 0 },
        { label: 'Low',      data: lowSeries,
          borderColor: '#94a3b8', backgroundColor: '#94a3b822',
          borderWidth: 2, pointRadius: 4, tension: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { grid: { color: '#334155' }, ticks: { color: '#e2e8f0', font: { size: 11 } } },
        y: {
          // Linear, not logarithmic: these series are expected to reach 0
          // (that's the success state) and Chart.js log axes cannot plot 0.
          type: 'linear',
          beginAtZero: true,
          grid: { color: '#334155' },
          ticks: { color: '#94a3b8', font: { size: 10 },
                   callback: v => v >= 1e3 ? (v/1e3).toFixed(0)+'K' : v },
          title: { display: true, text: 'Open Alerts', color: '#94a3b8', font: { size: 11 } },
        },
      },
      plugins: {
        legend:     { labels: { color: '#94a3b8', font: { size: 11 }, boxWidth: 12, padding: 10 } },
        tooltip:    { ...DARK, callbacks: { label: i => ' ' + i.dataset.label + ': ' + fmtN(i.raw) } },
        annotation: { annotations: annots },
      },
    },
  });
}
