// Inlined into the dashboard page by build_dashboard.py, after the data constants
// (SNAPSHOTS, DATES, CURRENT_DATE, ORG, TREND_SERIES, ANNOTATIONS, MOVED).
// Pure helpers: formatting, escaping, dates and baselines. No DOM.

// ── Utilities ─────────────────────────────────────────────────────────────────
const fmt  = n => n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(0)+'K':String(n);
const fmtN = n => Number(n).toLocaleString('en-GB');  // one format for every viewer
// Repo, package and secret-type names come from scanner data. They reach innerHTML
// below, so every one passes through esc() first.
const ESC  = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
const esc  = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ESC[c]);
const DARK = {backgroundColor:'#1e293b',borderColor:'#334155',borderWidth:1,
              titleColor:'#e2e8f0',bodyColor:'#94a3b8',padding:10,displayColors:false};

// Parse YYYYMMDD slug into a Date.
// A section's share-link id: a slug of its title. Only [a-z0-9-] survives, so an id
// is inert in an attribute selector and an inline onclick, wherever it came from.
function slugPanel(s) {
  return String(s == null ? '' : s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48);
}
function panelLink(id) {
  const s = slugPanel(id);
  return '<button type="button" class="panel-link" title="Copy a link to this section" onclick="sharePanel(\'' + s + '\')">🔗</button>';
}

function slugToDate(s){return new Date(s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8)+'T00:00:00Z')}

// Format a delta block against an earlier snapshot ageDays before.
function deltaSub(curVal, baseVal, ageDays) {
  const d = curVal - baseVal;
  const pct = baseVal > 0 ? (Math.abs(d) / baseVal * 100).toFixed(1) : null;
  const dir = d > 0 ? '↑' : d < 0 ? '↓' : '→';
  const col = d > 0 ? 'var(--crit)' : d < 0 ? 'var(--low)' : 'var(--muted)';
  const txt = d === 0 ? 'no change' : `${dir} ${fmtN(Math.abs(d))}` + (pct == null ? '' : ` (${pct}%)`);  // no percentage from zero
  return `<span style="color:${col}">${txt}</span> vs ${ageDays}d ago`;
}
