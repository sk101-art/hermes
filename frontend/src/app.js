import './styles.css';

const API = localStorage.getItem('hermes_api_url') || 'http://127.0.0.1:8765';
const state = { view: 'today', data: {}, selectedStory: null, query: '', loading: false, offline: false, localStars: JSON.parse(localStorage.getItem('hermes-stars') || '{}') };

const navItems = [
  ['today', '⌂', 'Today', 'Daily intelligence'],
  ['briefing', '◒', 'Morning briefing', 'A focused read'],
  ['search', '⌕', 'Search', 'Query the corpus'],
  ['projects', '▦', 'My projects', 'Context intelligence'],
  ['saved', '☆', 'Saved library', 'Longitudinal view'],
  ['changes', '↗', 'Changes', 'What moved'],
  ['runtime', '⌁', 'Runtime', 'Source health'],
];

const app = document.querySelector('#app');
const esc = (value = '') => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const date = value => value ? new Date(value).toLocaleDateString(undefined, { month:'short', day:'numeric', year:'numeric' }) : '—';
const time = value => value ? new Date(value).toLocaleTimeString(undefined, { hour:'2-digit', minute:'2-digit' }) : '—';
const titleCase = value => String(value || '').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
const arr = value => Array.isArray(value) ? value : [];
const starred = id => Boolean(state.localStars[id]);

function icon(name) {
  return `<span class="nav-icon" aria-hidden="true">${name}</span>`;
}

function shell() {
  app.innerHTML = `<div class="app-shell">
    <aside class="sidebar" id="sidebar">
      <div class="brand"><div class="brand-mark">H</div><div class="brand-copy"><strong>HERMES</strong><span>intelligence engine</span></div></div>
      <div class="nav-label">Workspace</div>
      <nav class="nav">${navItems.map(([id, glyph, label, hint]) => `<button class="nav-btn ${state.view === id ? 'active' : ''}" data-view="${id}" title="${hint}">${icon(glyph)}<span>${label}</span></button>`).join('')}</nav>
      <div class="sidebar-footer"><div class="local-pill"><span class="dot"></span><span>Local-first · localhost</span></div><div class="local-pill" style="color:var(--faint)">⌘ K&nbsp;&nbsp; Search anything</div></div>
    </aside>
    <main class="main">
      <header class="topbar"><div style="display:flex;gap:10px;align-items:center"><button class="icon-btn mobile-menu" id="mobile-menu" aria-label="Open navigation">☰</button><div class="crumb">HERMES <span style="color:var(--faint)">/</span> <strong>${navItems.find(x => x[0] === state.view)?.[2] || 'Today'}</strong></div></div><div class="top-actions"><button class="icon-btn" id="refresh" title="Refresh">↻</button><button class="icon-btn" id="command" title="Search">⌕</button><button class="secondary-btn" id="api-status"><span class="dot"></span> Local API</button></div></header>
      ${state.offline ? '<div class="offline-banner">The local API is unavailable. HERMES is showing a connection-safe empty state; start the FastAPI server to load live intelligence.</div>' : ''}
      <section class="content" id="content"></section>
    </main>
  </div>`;
  document.querySelectorAll('[data-view]').forEach(btn => btn.addEventListener('click', () => { state.view = btn.dataset.view; state.selectedStory = null; document.querySelector('#sidebar')?.classList.remove('open'); render(); loadView(); }));
  document.querySelector('#refresh').addEventListener('click', () => loadView(true));
  document.querySelector('#command').addEventListener('click', () => { state.view = 'search'; render(); loadView(); setTimeout(() => document.querySelector('#search-input')?.focus(), 30); });
  document.querySelector('#api-status').addEventListener('click', () => window.open(`${API}/docs`, '_blank'));
  document.querySelector('#mobile-menu').addEventListener('click', () => document.querySelector('#sidebar').classList.toggle('open'));
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, { signal: AbortSignal.timeout(7000), ...options });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function loadView(force = false) {
  if (state.loading && !force) return;
  state.loading = true; state.offline = false;
  const content = document.querySelector('#content'); if (content) content.innerHTML = '<div class="loading">Connecting to local intelligence engine</div>';
  try {
    if (state.view === 'today') state.data.today = await api('/inbox?limit=40');
    if (state.view === 'briefing') state.data.briefing = await api('/briefing').catch(() => ({}));
    if (state.view === 'projects') state.data.projects = await api('/projects');
    if (state.view === 'saved') state.data.saved = await api('/saved?limit=50');
    if (state.view === 'changes') state.data.changes = await api('/changes?hours=168&limit=40');
    if (state.view === 'runtime') state.data.runtime = await Promise.all([api('/health'), api('/runtime'), api('/sources')]);
    if (state.view === 'search' && state.query) state.data.search = await api(`/search?q=${encodeURIComponent(state.query)}&limit=30&explain=true`);
  } catch (error) { state.offline = true; state.data.error = error.message; }
  state.loading = false; shell(); render();
}

function header(eyebrow, title, subtitle, meta = '') {
  return `<div class="page-header"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p class="page-subtitle">${subtitle}</p></div>${meta ? `<div class="header-meta">${meta}</div>` : ''}</div>`;
}
function starButton(id) { return `<button class="star ${starred(id) ? 'on' : ''}" data-star="${esc(id)}" aria-label="${starred(id) ? 'Unsave' : 'Save'}">${starred(id) ? '★' : '☆'}</button>`; }
function bindStars() { document.querySelectorAll('[data-star]').forEach(btn => btn.addEventListener('click', e => { e.stopPropagation(); const id = btn.dataset.star; state.localStars[id] = !state.localStars[id]; if (!state.localStars[id]) delete state.localStars[id]; localStorage.setItem('hermes-stars', JSON.stringify(state.localStars)); render(); })); }

function normalizeStory(item) {
  return { id: item.story_cluster_id || item.cluster_id || item.id, title: item.title || item.canonical_title || 'Untitled development', why: item.why_it_matters || item.reason || item.summary || item.text || 'Open this development to inspect evidence, provenance, and project impact.', sources: arr(item.sources || item.source_names || item.source ? [item.source] : []), verification: item.verification_status || item.status || (item.verification_score >= .7 ? 'supported' : 'unverified'), maturity: item.maturity_stage || item.maturity || 'concept', risk: item.risk || (item.risk_score > .65 ? 'high' : item.risk_score > .35 ? 'medium' : 'low'), project: item.project_relevance || item.project_impact_score > 0 ? 'Project relevance' : '', date: item.created_at || item.updated_at || item.published_at, raw:item };
}
function storyCard(item) { const s = normalizeStory(item); return `<article class="panel story-card" data-story="${esc(s.id)}"><div class="card-top"><span class="source-line">${esc(s.sources.slice(0,3).join(' · ') || 'HERMES cluster')}</span><span>${date(s.date)}</span></div><h3 class="story-title">${esc(s.title)}</h3><p class="story-why">${esc(s.why)}</p><div class="card-bottom"><span class="tag ${/support|verified/i.test(s.verification) ? 'verified' : ''}">${esc(titleCase(s.verification))}</span><span class="tag ${/concept|experimental/i.test(s.maturity) ? 'experimental' : ''}">${esc(titleCase(s.maturity))}</span>${s.risk && s.risk !== 'low' ? `<span class="tag risk">${esc(titleCase(s.risk))} risk</span>` : ''}${s.project ? `<span class="tag">Relevant</span>` : ''}${starButton(s.id)}</div></article>`; }
function bindStories() { document.querySelectorAll('[data-story]').forEach(card => card.addEventListener('click', async () => { state.selectedStory = card.dataset.story; try { state.data.detail = await api(`/stories/${encodeURIComponent(state.selectedStory)}`); } catch { state.data.detail = null; } render(); })); bindStars(); }

function renderToday() {
  const payload = state.data.today || {}; const items = arr(payload.inbox_items || payload.items || payload); const sections = {}; items.forEach(item => (sections[item.section || 'must_know'] ||= []).push(item));
  const visible = Object.entries(sections); return `${header('Daily intelligence', 'What matters today', 'A calibrated view of technical developments, weighted by evidence, relevance, and change.', `<strong>${payload.count ?? items.length}</strong>active signals<br>${new Date().toLocaleDateString(undefined,{weekday:'long',month:'short',day:'numeric'})}`)}
    <div class="hero-grid"><div class="panel stat-card"><div class="stat-label">Signal surface</div><div class="stat-value">${items.length || '—'}</div><div class="stat-detail">items in today’s inbox</div></div><div class="panel stat-card"><div class="stat-label">Unseen</div><div class="stat-value">${items.filter(i => i.state === 'unseen').length || '—'}</div><div class="stat-detail">ready for review</div></div><div class="panel stat-card"><div class="stat-label">Project signal</div><div class="stat-value">${items.filter(i => arr(i.matched_project_ids).length).length || '—'}</div><div class="stat-detail">matched to your context</div></div></div>
    ${state.offline ? `<div class="panel error">Unable to reach ${esc(API)}<br><small>${esc(state.data.error || '')}</small></div>` : visible.length ? visible.map(([section, values]) => `<div class="section-head"><div><h2>${esc(titleCase(section))}</h2><p>${values.length} signal${values.length === 1 ? '' : 's'} · progressive detail</p></div><button class="secondary-btn" data-section="${esc(section)}">View all</button></div><div class="feed-grid">${values.map(storyCard).join('')}</div>`).join('') : `<div class="panel empty">No intelligence is available for this view yet. Run ingestion, then refresh HERMES.</div>`}`;
}
function renderBriefing() { const b = state.data.briefing || {}; return `${header('Morning briefing', 'The day, distilled', 'A serious engineering read: what changed, what strengthened, and what deserves your attention next.', `<strong>${esc(b.total_items || '—')}</strong>briefing items<br>Generated ${time(b.generated_at)}`)}<div class="panel briefing"><div class="briefing-date">${esc(b.briefing_date || 'Today')}</div><h2 style="margin-top:10px">A concise map of the signal</h2><p>${esc(b.summary_text || 'No briefing summary is available for this date. HERMES will surface the most relevant developments here after the morning briefing job completes.')}</p></div><div class="section-head"><div><h2>Briefing sections</h2><p>Each section links back to the underlying inbox item and its evidence.</p></div></div><div class="panel table-panel"><table class="data-table"><thead><tr><th>Section</th><th>Items</th><th>Priority</th></tr></thead><tbody>${Object.entries(b.sections || {}).map(([k,v]) => `<tr><td>${esc(titleCase(k))}</td><td>${arr(v).length}</td><td><span class="tag ${/must|project/i.test(k) ? 'verified' : ''}">${/must|project/i.test(k) ? 'Read first' : 'Monitor'}</span></td></tr>`).join('') || '<tr><td colspan="3">No briefing sections returned by the API.</td></tr>'}</tbody></table></div>`; }
function renderSearch() { const results = arr(state.data.search?.results); return `${header('Corpus query', 'Search with context', 'Search ranking is a relevance signal, not a probability. Provenance stays visible so you can judge the result.', '')}<div class="panel search-panel"><input id="search-input" class="search-input" value="${esc(state.query)}" placeholder="Search technologies, claims, projects, or sources…"/><button class="primary-btn" id="search-submit">Search</button></div><div class="filter-row"><select id="search-mode"><option value="hybrid">Hybrid search</option><option value="semantic">Semantic only</option><option value="lexical">Lexical only</option></select><select id="search-verified"><option value="false">All verification states</option><option value="true">Verified only</option></select></div><div class="section-head"><div><h2>${state.query ? `Results for “${esc(state.query)}”` : 'Start with a question'}</h2><p>${state.query ? `${results.length} result${results.length === 1 ? '' : 's'} returned` : 'Try “vector database”, “compiler”, or the name of a project.'}</p></div></div><div class="feed-grid">${results.map(storyCard).join('') || `<div class="panel empty" style="grid-column:1/-1">${state.query ? 'No results matched this query.' : 'Search the local intelligence corpus to see ranked stories with provenance.'}</div>`}</div>`; }
function renderProjects() { const projects = arr(state.data.projects?.projects || state.data.projects); return `${header('Context intelligence', 'My projects', 'HERMES understands your engineering context without exposing private source contents in the interface.', `<strong>${projects.length || '—'}</strong>indexed project${projects.length === 1 ? '' : 's'}`)}<div class="project-grid">${projects.map(p => `<article class="panel project-card"><div class="project-meta">${esc(p.id || 'project')}</div><h3>${esc(p.name)}</h3><p>${esc(p.description || 'Local engineering project profile')}</p><div class="chip-list">${arr(p.languages).concat(arr(p.frameworks)).concat(arr(p.databases)).slice(0,8).map(x => `<span class="chip">${esc(x)}</span>`).join('')}</div><div class="project-meta" style="margin-top:18px">Last indexed · ${date(p.last_indexed_at)}</div></article>`).join('') || '<div class="panel empty" style="grid-column:1/-1">No project profiles are available yet.</div>'}</div>`; }
function renderSaved() { const items = arr(state.data.saved?.saved_items || state.data.saved); return `${header('Longitudinal library', 'Saved intelligence', 'Saved snapshots keep their original state visible beside the current story state.', `<strong>${items.length || '—'}</strong>saved item${items.length === 1 ? '' : 's'}`)}<div class="panel table-panel"><table class="data-table"><thead><tr><th>Snapshot</th><th>Saved</th><th>At save</th><th>Risk</th><th>Tags</th></tr></thead><tbody>${items.map(i => `<tr><td>${esc(i.title_snapshot || i.title || 'Untitled')}<div class="project-meta">${esc(i.story_cluster_id || i.entity_id || '')}</div></td><td>${date(i.saved_at)}</td><td><span class="tag">${esc(titleCase(i.maturity_snapshot || '—'))}</span> <span class="tag verified">${Math.round((i.verification_snapshot || 0)*100)} verification</span></td><td>${esc(i.risk_snapshot ?? '—')}</td><td>${arr(i.tags).map(t => `<span class="chip">${esc(t)}</span>`).join(' ') || '—'}</td></tr>`).join('') || '<tr><td colspan="5">No saved intelligence returned by the API.</td></tr>'}</tbody></table></div>`; }
function renderChanges() { const changes = arr(state.data.changes?.changes || state.data.changes); return `${header('Longitudinal signal', 'What moved', 'Track verification, contradiction, maturity, release, and risk changes instead of treating intelligence as static.', '')}<div class="panel">${changes.map(c => `<div class="change-row"><div class="change-type">${esc(titleCase(c.change_type || c.entity_type))}</div><div class="change-text">${esc(c.reason || 'A tracked state change was detected')}<span>${esc(c.old_value || '—')} → ${esc(c.new_value || '—')} · ${date(c.created_at)}</span></div><div class="importance">${c.importance >= .75 ? 'High importance' : 'Observed'}</div></div>`).join('') || '<div class="empty">No changes were returned for the selected time window.</div>'}</div>`; }
function renderRuntime() { const [health={}, runtime={}, sources={}] = state.data.runtime || []; const sourceRows = arr(sources.sources || sources); const jobs = arr(runtime.jobs || runtime.runtime_jobs || runtime); return `${header('Operational surface', 'Runtime & source health', 'A compact view of whether the local intelligence engine is fresh, healthy, and explainable.', '')}<div class="hero-grid"><div class="panel stat-card"><div class="stat-label">API status</div><div class="stat-value" style="font-size:24px">${esc(health.status || 'unknown')}</div><div class="stat-detail">local health check</div></div><div class="panel stat-card"><div class="stat-label">Last ingestion</div><div class="stat-value" style="font-size:20px">${time(runtime.last_ingestion_at || runtime.last_ingestion)}</div><div class="stat-detail">runtime snapshot</div></div><div class="panel stat-card"><div class="stat-label">Sources</div><div class="stat-value">${sourceRows.length || '—'}</div><div class="stat-detail">configured adapters</div></div></div><div class="section-head"><h2>Source checkpoints</h2></div><div class="panel table-panel"><table class="data-table"><thead><tr><th>Source</th><th>Health</th><th>Last success</th><th>Failures</th></tr></thead><tbody>${sourceRows.map(s => `<tr><td>${esc(s.source || s.name)}</td><td><span class="tag ${s.health_status === 'healthy' ? 'verified' : s.health_status === 'offline' ? 'risk' : ''}">${esc(titleCase(s.health_status || s.status || 'unknown'))}</span></td><td>${date(s.last_success_at)}</td><td>${s.consecutive_failures ?? '—'}</td></tr>`).join('') || '<tr><td colspan="4">No source health data returned by the API.</td></tr>'}</tbody></table></div>`; }
function renderDetail() { const d = state.data.detail || {}; const claims = arr(d.claims); const evidence = arr(d.evidence); return `${header('Technology detail', 'Inspect the story', 'A source-aware view of claims, evidence, relationships, and recent change.', '')}<button class="secondary-btn" id="back-to-view">← Back to ${navItems.find(x => x[0] === 'today')[2]}</button><div class="detail-layout" style="margin-top:14px"><article class="panel detail-main"><div class="source-line">${esc(arr(d.sources).join(' · ') || 'Story cluster')}</div><h2 class="story-title">${esc(d.canonical_title || d.title || 'Story detail')}</h2><p>${esc(d.summary || d.why_it_matters || 'The story detail endpoint returned structured intelligence. Explore claims and evidence below.')}</p><div class="metric-row"><div class="metric"><span>Verification</span><strong>${esc(d.verification_status || d.status || '—')}</strong></div><div class="metric"><span>Maturity</span><strong>${esc(d.maturity_stage || '—')}</strong></div><div class="metric"><span>Risk</span><strong>${esc(d.risk || d.risk_score || '—')}</strong></div><div class="metric"><span>Events</span><strong>${arr(d.event_ids).length || '—'}</strong></div></div><h3>Claims & evidence</h3>${claims.map(c => `<div class="evidence-row"><strong>${esc(c.claim_text || c.text || 'Claim')}</strong><span>${esc(titleCase(c.status || 'unverified'))} · ${c.self_reported ? 'Self-reported' : 'Independent'} · verification ${Math.round((c.verification_score || 0)*100)}%</span></div>`).join('') || '<div class="empty">No claims were attached to this story.</div>'}</article><aside class="panel detail-aside"><h3>Evidence trail</h3>${evidence.map(e => `<div class="evidence-row"><strong>${esc(e.source || 'Source')} · ${esc(e.stance || 'supports')}</strong><span>${esc(e.evidence_type || e.evidence_class || 'Evidence')} · quality ${Math.round((e.quality_score || 0)*100)}%</span>${e.excerpt ? `<p style="font-size:11px;margin:6px 0 0">“${esc(e.excerpt)}”</p>` : ''}</div>`).join('') || '<div class="empty" style="padding:20px 0">Evidence will appear here when returned by the backend.</div>'}</aside></div>`; }

function render() {
  const content = document.querySelector('#content'); if (!content) { shell(); return render(); }
  if (state.selectedStory) content.innerHTML = renderDetail(); else if (state.view === 'today') content.innerHTML = renderToday(); else if (state.view === 'briefing') content.innerHTML = renderBriefing(); else if (state.view === 'search') content.innerHTML = renderSearch(); else if (state.view === 'projects') content.innerHTML = renderProjects(); else if (state.view === 'saved') content.innerHTML = renderSaved(); else if (state.view === 'changes') content.innerHTML = renderChanges(); else if (state.view === 'runtime') content.innerHTML = renderRuntime();
  bindStories();
  document.querySelector('#search-submit')?.addEventListener('click', () => { state.query = document.querySelector('#search-input').value.trim(); loadView(); });
  document.querySelector('#search-input')?.addEventListener('keydown', e => { if (e.key === 'Enter') { state.query = e.target.value.trim(); loadView(); } });
  document.querySelector('#back-to-view')?.addEventListener('click', () => { state.selectedStory = null; render(); });
}

shell(); render(); loadView();
