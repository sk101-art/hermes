/**
 * HERMES Today Inbox View
 * Daily intelligence prioritization surface grouped by canonical section hierarchy.
 *
 * Truthfulness Invariant:
 * Prioritization surface, not a verification surface.
 * inbox_score, rank_score, and project_impact_score represent urgency, ordering, and project context.
 * Does not synthesize verification, maturity, or risk badges on Inbox cards.
 * Canonical investigation route remains #/story/{story_cluster_id}.
 */

import { api } from '../api/endpoints.js';
import { renderLoadingState, renderEmptyState, renderErrorState, renderOfflineState } from '../components/ui-states.js';
import { escapeHtml, formatDate, ensureArray, toTitleCase } from '../utils/adapters.js';

export const CANONICAL_INBOX_SECTIONS = [
  { key: 'must_know', label: 'Must Know' },
  { key: 'project_relevant', label: 'Project Relevant' },
  { key: 'corrections_updates', label: 'Corrections & Revisions' },
  { key: 'systems_compilers', label: 'Systems & Compilers' },
  { key: 'ai_ml', label: 'AI & Machine Learning' },
  { key: 'storage_databases', label: 'Storage & Databases' },
  { key: 'developer_tooling', label: 'Developer Tooling' },
  { key: 'research', label: 'Research & Theory' },
  { key: 'watchlist', label: 'Watchlist' },
];

export const CANONICAL_SECTION_ORDER = CANONICAL_INBOX_SECTIONS.map((s) => s.key);

export const ITEM_TYPE_META = {
  new_story: { label: 'New Story', classModifier: 'type-new-story' },
  story_update: { label: 'Story Update', classModifier: 'type-update' },
  claim_strengthened: { label: 'Corroboration Added', classModifier: 'type-corroboration' },
  claim_weakened: { label: 'Contradiction / Weakened', classModifier: 'type-caution type-weakened' },
  new_release: { label: 'New Release', classModifier: 'type-release' },
  new_risk: { label: 'Risk Change', classModifier: 'type-caution type-risk' },
  maturity_change: { label: 'Maturity Shift', classModifier: 'type-maturity' },
  correction: { label: 'Correction', classModifier: 'type-caution type-correction' },
};

export function formatItemType(itemType) {
  if (!itemType) return null;
  const meta = ITEM_TYPE_META[itemType];
  if (meta) {
    return `<span class="inbox-type-badge ${meta.classModifier}" data-item-type="${escapeHtml(itemType)}">${escapeHtml(meta.label)}</span>`;
  }
  return `<span class="inbox-type-badge type-generic" data-item-type="${escapeHtml(itemType)}">${escapeHtml(toTitleCase(itemType))}</span>`;
}

export function formatReasonCode(code) {
  if (!code) return '';
  if (code.startsWith('intel_change:verification_strengthened')) return 'Verification Reevaluated';
  if (code.startsWith('intel_change:maturity_increased')) return 'Maturity Progressed';
  if (code.startsWith('intel_change:')) return toTitleCase(code.replace('intel_change:', '').replace(/_/g, ' '));
  if (code.startsWith('direct_dependency_match:')) {
    const proj = code.replace('direct_dependency_match:', '').replace('project:', '');
    return `Direct Dependency: ${proj}`;
  }
  if (code.startsWith('dependency_match:')) {
    return `Dependency: ${code.replace('dependency_match:', '')}`;
  }
  if (code.startsWith('project_match:')) {
    const kind = code.replace('project_match:', '').replace(/_/g, ' ');
    return `Project Context: ${toTitleCase(kind)}`;
  }
  if (code.startsWith('verified_claim:')) return 'Verified Claim Found';
  if (code === 'recent_discovery') return 'Recent Discovery';
  if (code === 'official_release') return 'Official Release';
  return toTitleCase(code.replace(/_/g, ' '));
}

export function formatExpiryLifecycle(expiresAtStr) {
  if (!expiresAtStr) return '';
  const expDate = new Date(expiresAtStr);
  const now = new Date();
  const diffMs = expDate.getTime() - now.getTime();
  const diffHours = Math.round(diffMs / (1000 * 60 * 60));
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));

  if (diffMs <= 0) {
    return '<span class="inbox-expiry-tag text-muted" title="Completed inbox retention window">Inbox cycle completed</span>';
  }
  if (diffHours < 24) {
    return '<span class="inbox-expiry-tag inbox-expiring-soon" title="Leaves inbox today">Leaves inbox today</span>';
  }
  return `<span class="inbox-expiry-tag" title="Expires from active inbox in ${diffDays} days">Leaves inbox in ${diffDays} days</span>`;
}

function getSectionPrecedence(sectionKey) {
  if (!sectionKey) return 999;
  const idx = CANONICAL_SECTION_ORDER.indexOf(sectionKey.toLowerCase().trim());
  return idx >= 0 ? idx : 500;
}

export function consolidateInboxItems(items) {
  if (!items || !items.length) return { consolidatedList: [], sections: {} };

  const clusterGroups = new Map();
  const ungrouped = [];

  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const cid = item.story_cluster_id;
    if (!cid) {
      ungrouped.push({ ...item, _backendOrder: i });
      continue;
    }
    if (!clusterGroups.has(cid)) {
      clusterGroups.set(cid, []);
    }
    clusterGroups.get(cid).push({ ...item, _backendOrder: i });
  }

  const consolidatedList = [];

  for (const [cid, group] of clusterGroups.entries()) {
    if (group.length === 1) {
      consolidatedList.push(group[0]);
      continue;
    }

    let bestItem = group[0];
    let bestSectionRank = getSectionPrecedence(bestItem.section);

    for (let k = 1; k < group.length; k++) {
      const cand = group[k];
      const candRank = getSectionPrecedence(cand.section);
      if (candRank < bestSectionRank) {
        bestSectionRank = candRank;
        bestItem = cand;
      } else if (candRank === bestSectionRank && cand._backendOrder < bestItem._backendOrder) {
        bestItem = cand;
      }
    }

    const allItemTypes = new Set();
    const allReasons = new Set();
    const allProjects = new Set();
    let anyStarred = false;
    let activeSavedId = null;

    for (const member of group) {
      if (member.item_type) allItemTypes.add(member.item_type);
      if (member.reason_codes && Array.isArray(member.reason_codes)) {
        member.reason_codes.forEach((r) => allReasons.add(r));
      }
      if (member.matched_project_ids && Array.isArray(member.matched_project_ids)) {
        member.matched_project_ids.forEach((p) => allProjects.add(p));
      }
      if (member.is_starred) anyStarred = true;
      if (member.saved_item_id) activeSavedId = member.saved_item_id;
    }

    allItemTypes.delete(bestItem.item_type);

    const consolidatedItem = {
      ...bestItem,
      is_starred: Boolean(bestItem.is_starred || anyStarred),
      saved_item_id: bestItem.saved_item_id || activeSavedId,
      reason_codes: Array.from(allReasons),
      matched_project_ids: Array.from(allProjects),
      secondaryItemTypes: Array.from(allItemTypes),
      consolidatedCount: group.length,
    };
    consolidatedList.push(consolidatedItem);
  }

  for (const ug of ungrouped) {
    consolidatedList.push(ug);
  }

  // Preserve relative backend order
  consolidatedList.sort((a, b) => a._backendOrder - b._backendOrder);

  const sections = {};
  for (const item of consolidatedList) {
    const sec = item.section || 'must_know';
    if (!sections[sec]) sections[sec] = [];
    sections[sec].push(item);
  }

  return { consolidatedList, sections };
}

export function renderInboxCard(item) {
  if (!item) return '';

  const id = item.id || '';
  const cid = item.story_cluster_id || '';
  const title = item.title || 'Untitled Intelligence Signal';
  const section = item.section || 'must_know';
  const state = item.state || 'unseen';
  const itemType = item.item_type || 'new_story';
  const isStarred = Boolean(item.is_starred || item.saved_item_id);
  const savedId = item.saved_item_id || '';
  const isResolvable = Boolean(item.story_available && cid);
  const priorityScore = typeof item.inbox_score === 'number' ? item.inbox_score : null;
  const rankScore = typeof item.rank_score === 'number' ? item.rank_score : null;
  const projectImpact = typeof item.project_impact_score === 'number' ? item.project_impact_score : null;
  const matchedProjects = ensureArray(item.matched_project_ids);
  const reasons = ensureArray(item.reason_codes);
  const secondaryTypes = ensureArray(item.secondaryItemTypes);
  const expiryHtml = formatExpiryLifecycle(item.expires_at);

  const typeHtml = formatItemType(itemType);
  const stateBadge = state === 'unseen'
    ? '<span class="inbox-state-badge state-unseen" data-state="unseen">Unseen</span>'
    : '';
  const savedBadge = isStarred
    ? '<span class="inbox-state-badge state-saved" data-state="starred" aria-label="Saved in personal library">&#9733; Saved</span>'
    : '';

  const reasonChips = reasons.map((rc) => {
    const isWeakening = rc.includes('weakened') || rc.includes('contradict') || rc.includes('risk');
    return `<span class="inbox-reason-chip ${isWeakening ? 'reason-caution' : ''}" data-reason-code="${escapeHtml(rc)}">${escapeHtml(formatReasonCode(rc))}</span>`;
  });

  const secondaryTypeChips = secondaryTypes.map((st) => {
    const meta = ITEM_TYPE_META[st] || { label: toTitleCase(st), classModifier: 'type-generic' };
    return `<span class="inbox-secondary-type-chip ${meta.classModifier}" data-secondary-type="${escapeHtml(st)}">+ ${escapeHtml(meta.label)}</span>`;
  });

  let projectContextHtml = '';
  if (matchedProjects.length > 0 || (projectImpact !== null && projectImpact > 0)) {
    const scoreText = projectImpact !== null && projectImpact > 0
      ? `<span class="project-impact-pill">Project Relevance: <strong>${Math.round(projectImpact * 100)}%</strong></span>`
      : '';
    projectContextHtml = `
      <div class="inbox-project-context" data-matched-projects="${escapeHtml(matchedProjects.join(','))}">
        <span class="project-context-label">Project Context:</span>
        <span class="mono text-xs project-id-list">${escapeHtml(matchedProjects.join(', ') || 'Matched')}</span>
        ${scoreText}
      </div>
    `;
  }

  let priorityPill = '';
  if (priorityScore !== null) {
    priorityPill = `<span class="inbox-score-pill" title="Surfacing priority score calculated by HERMES ranking pipeline"><span class="score-label">Priority:</span> <strong>${Math.round(priorityScore * 100)}%</strong></span>`;
  }

  let rankPill = '';
  if (rankScore !== null && rankScore !== priorityScore) {
    rankPill = `<span class="inbox-rank-pill text-muted text-xs"><span class="score-label">Order Rank:</span> ${rankScore.toFixed(2)}</span>`;
  }

  const titleHtml = isResolvable
    ? `<a href="#/story/${encodeURIComponent(cid)}" class="inbox-title-link">${escapeHtml(title)}</a>`
    : escapeHtml(title);

  const storyActionHtml = isResolvable
    ? `<a href="#/story/${encodeURIComponent(cid)}" class="btn btn-sm btn-primary story-nav-btn" aria-label="Open Story Dossier for ${escapeHtml(title)}">Open Story Dossier &rarr;</a>`
    : `<span class="inbox-unavailable-note text-muted text-sm" role="status">Story dossier currently unavailable</span>`;

  const saveBtnHtml = isStarred
    ? `<button type="button" class="btn btn-sm btn-secondary btn-save-inbox is-saved" data-inbox-id="${escapeHtml(id)}" data-cluster-id="${escapeHtml(cid)}" data-saved-id="${escapeHtml(savedId)}" aria-pressed="true" aria-label="Saved in Library for ${escapeHtml(title)}">&#9733; Saved in Library</button>`
    : `<button type="button" class="btn btn-sm btn-secondary btn-save-inbox" data-inbox-id="${escapeHtml(id)}" data-cluster-id="${escapeHtml(cid)}" aria-pressed="false" aria-label="Save to Library: ${escapeHtml(title)}">&#9734; Save to Library</button>`;

  return `
    <article class="inbox-card" data-inbox-id="${escapeHtml(id)}" data-cluster-id="${escapeHtml(cid)}" data-section="${escapeHtml(section)}" data-item-type="${escapeHtml(itemType)}" aria-labelledby="inbox-title-${escapeHtml(id)}">
      <div class="inbox-card-top">
        <div class="inbox-badge-group">
          ${typeHtml || ''}
          ${stateBadge}
          ${savedBadge}
        </div>
        <div class="inbox-meta-right">
          ${expiryHtml}
          ${priorityPill}
          ${rankPill}
        </div>
      </div>

      <h3 id="inbox-title-${escapeHtml(id)}" class="inbox-title">${titleHtml}</h3>

      ${reasonChips.length || secondaryTypeChips.length ? `
        <div class="inbox-rationale-box">
          <span class="inbox-rationale-label">Why Surfaced:</span>
          <div class="inbox-chips-wrap">
            ${reasonChips.join('')}
            ${secondaryTypeChips.join('')}
          </div>
        </div>
      ` : ''}

      ${projectContextHtml}

      <div class="inbox-card-bottom">
        <div class="inbox-action-group">
          ${storyActionHtml}
          ${cid ? saveBtnHtml : ''}
        </div>
      </div>
    </article>
  `;
}

export function parseInboxHashParams() {
  const hash = (typeof window !== 'undefined' && window.location ? window.location.hash : '') || '';
  const queryIdx = hash.indexOf('?');
  if (queryIdx === -1) return { unseen_only: false, section: null, project: null };

  const searchParams = new URLSearchParams(hash.slice(queryIdx + 1));
  const unseen_only = searchParams.get('unseen') === 'true' || searchParams.get('unseen_only') === 'true';
  const section = searchParams.get('section') || null;
  const project = searchParams.get('project') || null;

  return { unseen_only, section, project };
}

export function updateInboxHash(params) {
  if (typeof window === 'undefined' || !window.location) return;
  const q = new URLSearchParams();
  if (params.unseen_only) q.set('unseen', 'true');
  if (params.section) q.set('section', params.section);
  if (params.project) q.set('project', params.project);

  const qs = q.toString();
  const targetHash = qs ? `#/today?${qs}` : `#/today`;
  if (window.location.hash !== targetHash) {
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, '', targetHash);
    }
    window.location.hash = targetHash;
  }
}

let currentInboxRequestId = 0;

export async function renderTodayView(container, store) {
  const initialParams = parseInboxHashParams();
  let availableProjects = [];

  try {
    const projRes = await api.getProjects();
    availableProjects = ensureArray(projRes.projects || projRes);
  } catch (e) {
    availableProjects = [];
  }

  const todayDateStr = formatDate(new Date().toISOString());

  container.innerHTML = `
    <div class="page-header-container">
      <div>
        <span class="eyebrow">Daily Intelligence</span>
        <h1>What Matters Today</h1>
        <p class="lead">A calibrated view of technical developments, ordered by urgency, relevance, and recent change.</p>
      </div>
      <div class="page-header-meta">
        <span id="today-date-badge">${todayDateStr}</span>
      </div>
    </div>

    <div class="hero-stats-grid" id="today-stats-grid">
      <div class="stat-card">
        <div class="stat-label">Signal Surface</div>
        <div class="stat-value" id="stat-signal-surface">-</div>
        <div class="stat-detail">items in today’s inbox</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Unseen</div>
        <div class="stat-value" id="stat-unseen">-</div>
        <div class="stat-detail">ready for engineering review</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Project Matches</div>
        <div class="stat-value" id="stat-project-matches">-</div>
        <div class="stat-detail">matched to your local projects</div>
      </div>
    </div>

    <div class="inbox-toolbar" role="region" aria-label="Inbox Filters">
      <div class="inbox-toolbar-row">
        <div class="inbox-filter-control">
          <label for="sel-inbox-section" class="filter-label">Section:</label>
          <select id="sel-inbox-section" class="form-select filter-select" aria-label="Filter by Inbox Section">
            <option value="">All Sections</option>
            ${CANONICAL_INBOX_SECTIONS.map((s) => `
              <option value="${escapeHtml(s.key)}" ${initialParams.section === s.key ? 'selected' : ''}>${escapeHtml(s.label)}</option>
            `).join('')}
          </select>
        </div>

        <div class="inbox-filter-control">
          <label for="sel-inbox-project" class="filter-label">Project Context:</label>
          <select id="sel-inbox-project" class="form-select filter-select" aria-label="Filter by Project Context">
            <option value="">All Projects</option>
            ${availableProjects.map((p) => {
              const pid = typeof p === 'string' ? p : (p.id || p.name);
              const pname = typeof p === 'string' ? p : (p.name || p.id);
              return `<option value="${escapeHtml(pid)}" ${initialParams.project === pid ? 'selected' : ''}>${escapeHtml(pname)}</option>`;
            }).join('')}
          </select>
        </div>

        <div class="inbox-filter-control checkbox-control">
          <label class="checkbox-label">
            <input type="checkbox" id="chk-unseen-only" ${initialParams.unseen_only ? 'checked' : ''} aria-label="Show only unseen signals" />
            <span>Unseen Only</span>
          </label>
        </div>

        <div class="inbox-filter-actions">
          <button type="button" id="btn-reset-inbox-filters" class="btn btn-sm btn-ghost" aria-label="Reset all inbox filters">Reset Filters</button>
        </div>
      </div>
    </div>

    <div id="inbox-live-region" class="sr-only" aria-live="polite" aria-atomic="true"></div>

    <div id="inbox-feed-container" class="inbox-feed-container">
      ${renderLoadingState('Loading daily intelligence feed…')}
    </div>
  `;

  async function executeFetch(filterState) {
    const reqId = ++currentInboxRequestId;
    const feedContainer = container.querySelector('#inbox-feed-container');
    const liveRegion = container.querySelector('#inbox-live-region');

    if (feedContainer) {
      feedContainer.innerHTML = renderLoadingState('Loading prioritized daily intelligence…');
    }

    try {
      const params = { limit: 40 };
      if (filterState.unseen_only) params.unseen_only = true;
      if (filterState.section) params.section = filterState.section;
      if (filterState.project) params.project = filterState.project;

      const payload = await api.getInbox(params);
      if (reqId !== currentInboxRequestId) return; // Stale response protection

      store.setViewData('today', payload);
      store.setConnection('healthy');

      const rawItems = ensureArray(payload.inbox_items || payload.items || payload);
      const { consolidatedList, sections } = consolidateInboxItems(rawItems);

      // Update hero stats
      const signalStat = container.querySelector('#stat-signal-surface');
      const unseenStat = container.querySelector('#stat-unseen');
      const projectStat = container.querySelector('#stat-project-matches');

      if (signalStat) signalStat.textContent = String(rawItems.length);
      if (unseenStat) unseenStat.textContent = String(rawItems.filter((i) => i.state === 'unseen').length);
      if (projectStat) {
        projectStat.textContent = String(rawItems.filter((i) => (i.matched_project_ids && i.matched_project_ids.length) || (typeof i.project_impact_score === 'number' && i.project_impact_score > 0)).length);
      }

      if (!consolidatedList.length) {
        feedContainer.innerHTML = renderEmptyState(
          'No Intelligence Signals Available',
          'No signals match the current inbox filter criteria. Run ingestion or reset filters to view active developments.'
        );
        if (liveRegion) liveRegion.textContent = 'Zero intelligence signals match current filters.';
        return;
      }

      // Render sections in deterministic order
      const renderedSections = [];
      const knownSectionKeys = new Set(CANONICAL_SECTION_ORDER);

      // 1. Render canonical sections that have items
      for (const secKey of CANONICAL_SECTION_ORDER) {
        if (sections[secKey] && sections[secKey].length) {
          const secMeta = CANONICAL_INBOX_SECTIONS.find((s) => s.key === secKey);
          const secLabel = secMeta ? secMeta.label : toTitleCase(secKey);
          const secItems = sections[secKey];

          renderedSections.push(`
            <section class="inbox-section" data-section-key="${escapeHtml(secKey)}" aria-labelledby="sec-head-${escapeHtml(secKey)}">
              <div class="section-header">
                <div>
                  <h2 id="sec-head-${escapeHtml(secKey)}">${escapeHtml(secLabel)}</h2>
                  <p class="text-muted text-sm" style="margin:0;">
                    ${secItems.length} signal${secItems.length === 1 ? '' : 's'} · ordered by priority
                  </p>
                </div>
              </div>
              <div class="grid-2">
                ${secItems.map(renderInboxCard).join('')}
              </div>
            </section>
          `);
        }
      }

      // 2. Render any unknown sections deterministically sorted
      const unknownKeys = Object.keys(sections).filter((k) => !knownSectionKeys.has(k)).sort();
      for (const unkKey of unknownKeys) {
        if (sections[unkKey] && sections[unkKey].length) {
          const unkItems = sections[unkKey];
          renderedSections.push(`
            <section class="inbox-section" data-section-key="${escapeHtml(unkKey)}" aria-labelledby="sec-head-${escapeHtml(unkKey)}">
              <div class="section-header">
                <div>
                  <h2 id="sec-head-${escapeHtml(unkKey)}">${escapeHtml(toTitleCase(unkKey))}</h2>
                  <p class="text-muted text-sm" style="margin:0;">
                    ${unkItems.length} signal${unkItems.length === 1 ? '' : 's'} · ordered by priority
                  </p>
                </div>
              </div>
              <div class="grid-2">
                ${unkItems.map(renderInboxCard).join('')}
              </div>
            </section>
          `);
        }
      }

      feedContainer.innerHTML = renderedSections.join('');
      if (liveRegion) {
        liveRegion.textContent = `Showing ${consolidatedList.length} prioritized intelligence signals across ${renderedSections.length} sections.`;
      }
    } catch (err) {
      if (reqId !== currentInboxRequestId) return;
      if (err.isNetworkError) {
        store.setConnection('offline', err.message);
        feedContainer.innerHTML = renderOfflineState(undefined, err.message);
      } else {
        store.setConnection('degraded', err.message);
        feedContainer.innerHTML = renderErrorState('Failed to Load Inbox Feed', err.message);
      }
      if (liveRegion) liveRegion.textContent = `Error loading inbox feed: ${err.message}`;
    }
  }

  // Setup Event Listeners
  const selSection = container.querySelector('#sel-inbox-section');
  const selProject = container.querySelector('#sel-inbox-project');
  const chkUnseen = container.querySelector('#chk-unseen-only');
  const btnReset = container.querySelector('#btn-reset-inbox-filters');

  function getCurrentFilterState() {
    return {
      unseen_only: chkUnseen ? chkUnseen.checked : false,
      section: selSection && selSection.value ? selSection.value : null,
      project: selProject && selProject.value ? selProject.value : null,
    };
  }

  function handleFilterChange() {
    const fs = getCurrentFilterState();
    updateInboxHash(fs);
    executeFetch(fs);
  }

  if (selSection) selSection.addEventListener('change', handleFilterChange);
  if (selProject) selProject.addEventListener('change', handleFilterChange);
  if (chkUnseen) chkUnseen.addEventListener('change', handleFilterChange);

  if (btnReset) {
    btnReset.addEventListener('click', () => {
      if (selSection) selSection.value = '';
      if (selProject) selProject.value = '';
      if (chkUnseen) chkUnseen.checked = false;
      handleFilterChange();
    });
  }

  // Save to Library Event Delegation
  container.addEventListener('click', async (e) => {
    const saveBtn = e.target.closest('.btn-save-inbox');
    if (!saveBtn) return;

    const inboxId = saveBtn.dataset.inboxId;
    const clusterId = saveBtn.dataset.clusterId;
    if (!clusterId) return;

    if (saveBtn.classList.contains('is-saved')) {
      return; // Already active in library
    }

    const originalText = saveBtn.innerHTML;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    const liveRegion = container.querySelector('#inbox-live-region');

    try {
      const res = await api.saveItem({
        story_cluster_id: clusterId,
        inbox_item_id: inboxId || undefined,
      });

      saveBtn.classList.add('is-saved');
      saveBtn.setAttribute('aria-pressed', 'true');
      saveBtn.innerHTML = '&#9733; Saved in Library';
      if (res && res.saved_item && res.saved_item.id) {
        saveBtn.dataset.savedId = res.saved_item.id;
      }
      saveBtn.disabled = false;

      // Update card header saved badge
      const card = saveBtn.closest('.inbox-card');
      if (card) {
        const badgeGroup = card.querySelector('.inbox-badge-group');
        if (badgeGroup && !badgeGroup.querySelector('.state-saved')) {
          badgeGroup.insertAdjacentHTML('beforeend', '<span class="inbox-state-badge state-saved" data-state="starred" aria-label="Saved in personal library">&#9733; Saved</span>');
        }
      }

      if (liveRegion) liveRegion.textContent = 'Story saved to library.';
    } catch (err) {
      saveBtn.disabled = false;
      saveBtn.innerHTML = originalText;
      if (liveRegion) liveRegion.textContent = `Failed to save story: ${err.message}`;
    }
  });

  // Initial fetch
  await executeFetch(initialParams);
}
