// ── NatLocs — Overture Maps retail/restaurant map layer ──────────────────────
// Shared across every map surface (Search, Property detail, Account/Contact).
// Depends on: Leaflet.js, API from app.js, BrokerSegments from broker_segments.js.
//
// Usage:
//   1. Load broker_segments.js, then national_locations_layer.js.
//   2. After L.map(...) is ready: NatLocs.init(leafletMapInstance)
//      → injects a two-level filter panel into the map container.
//
// Singleton — one map per page.

const NatLocs = (() => {

  // ── Category emoji fallback (keyed on category_top) ─────────────────────
  // Used when a location has no website (and therefore no logo).
  // Keys are the EXACT strings written to national_locations.category_top.
  const CATEGORY_EMOJI = {
    food_and_drink:             '🍽️',
    shopping:                   '🛍️',
    travel_and_transportation:  '✈️',
    lifestyle_services:         '💈',
    services_and_business:      '🏢',
  };
  const FALLBACK_EMOJI = '📍';

  // ── State ─────────────────────────────────────────────────────────────────
  let _map        = null;
  let _markerData = [];      // [{marker, loc}] — ALL fetched; only some on map
  let _visible    = false;   // master layer on/off
  let _panel      = null;
  let _panelOpen  = true;

  // Filter state — persisted across viewport pans so user choices stick.
  // _disabledTops: Set of category_top strings the user has turned OFF (tier-1).
  // _segFilter:    Map<category_top, Set<segId> | null>
  //   null (or absent key) = no segment filter for that top → show all.
  //   Non-null Set = only show these segment ids under that top.
  let _disabledTops = new Set();
  let _segFilter    = {};   // key: category_top → null | Set<segId>
  let _nameFilter   = '';   // text search — empty = no constraint

  let _boundsKey     = null;
  let _styleInjected = false;

  // ── CSS ───────────────────────────────────────────────────────────────────
  function _injectStyles() {
    if (_styleInjected) return;
    _styleInjected = true;
    const s = document.createElement('style');
    s.textContent = `
/* ── Panel ── */
.natloc-panel {
  position:absolute; bottom:30px; left:10px; z-index:500;
  background:var(--surface,#fff); border:1px solid var(--border,rgba(27,34,53,0.08));
  border-radius:var(--radius-md,12px); box-shadow:0 2px 8px rgba(0,0,0,0.14);
  width:210px; font-family:var(--font-system,-apple-system,sans-serif);
  font-size:12px; color:var(--ink,#1B2235); overflow:hidden;
}
.natloc-panel-header {
  display:flex; align-items:center; justify-content:space-between;
  padding:8px 10px; background:var(--paper,#F3F2EE);
  border-bottom:1px solid var(--border,rgba(27,34,53,0.08)); cursor:pointer;
}
.natloc-panel-title {
  display:flex; align-items:center; gap:6px; font-weight:600; font-size:12.5px;
}
.natloc-panel-collapse {
  background:none; border:none; cursor:pointer; font-size:11px;
  color:var(--text-secondary,#5C6470); padding:0 2px; line-height:1;
}
.natloc-panel-body {
  max-height:55vh; overflow-y:auto; padding:6px 0;
}
.natloc-panel-body.hidden { display:none; }

/* Search box */
.natloc-search-row {
  padding:7px 10px 5px;
  border-bottom:1px solid var(--border,rgba(27,34,53,0.08));
}
.natloc-search-input {
  width:100%; box-sizing:border-box; padding:5px 8px;
  font-size:12px; font-family:var(--font-system,-apple-system,sans-serif);
  border:1px solid var(--border,rgba(27,34,53,0.08)); border-radius:var(--radius-sm,8px);
  background:var(--paper,#F3F2EE); color:var(--ink,#1B2235); outline:none;
}
.natloc-search-input:focus { border-color:var(--accent,#1F5E52); background:#fff; }

/* Master toggle */
.natloc-master-row {
  display:flex; align-items:center; gap:7px;
  padding:6px 10px 5px;
  border-bottom:1px solid var(--border,rgba(27,34,53,0.08));
}
.natloc-master-row label {
  display:flex; align-items:center; gap:6px; cursor:pointer; user-select:none;
  font-size:12px; font-weight:500;
}

/* Tier-1 group */
.natloc-group { border-bottom:1px solid var(--border,rgba(27,34,53,0.08)); }
.natloc-group:last-of-type { border-bottom:none; }
.natloc-group-header {
  display:flex; align-items:center; gap:6px;
  padding:5px 10px; cursor:pointer; user-select:none;
  font-weight:600; font-size:11.5px;
}
.natloc-group-header input[type=checkbox] { margin:0; }
.natloc-group-header:hover { background:var(--paper,#F3F2EE); }

/* Tier-2 segments */
.natloc-segs { padding:0 6px 4px 24px; }
.natloc-seg-row {
  display:flex; align-items:center; gap:6px;
  padding:2px 4px; border-radius:4px;
}
.natloc-seg-row label {
  display:flex; align-items:center; gap:5px;
  cursor:pointer; user-select:none; font-size:11px;
}
.natloc-seg-row:hover { background:var(--paper,#F3F2EE); }
.natloc-seg-row.disabled label { opacity:0.38; pointer-events:none; }

/* Legend */
.natloc-legend {
  padding:6px 10px 8px; border-top:1px solid var(--border,rgba(27,34,53,0.08));
  font-size:10.5px; color:var(--text-secondary,#5C6470);
}
.natloc-legend-note { margin-top:3px; font-style:italic; }

/* ── Markers ── */
.natloc-dot {
  width:38px; height:38px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  font-size:17px; border:2px solid #fff;
  box-shadow:0 2px 5px rgba(0,0,0,0.3); cursor:pointer; flex-shrink:0;
}
.natloc-logo-chip {
  width:38px; height:38px; border-radius:10px;
  background:#fff; border:1px solid rgba(27,34,53,0.12);
  box-shadow:0 2px 5px rgba(0,0,0,0.18); cursor:pointer;
  display:flex; align-items:center; justify-content:center; flex-shrink:0;
  overflow:hidden;
}
.natloc-logo-chip img { width:30px; height:30px; object-fit:contain; }
.leaflet-div-icon { background:none; border:none; }

/* ── Popup ── */
.natloc-popup { min-width:180px; font-family:var(--font-system,-apple-system,sans-serif); }
.natloc-popup-brand { font-size:13.5px; font-weight:600; color:var(--ink,#1B2235); margin-bottom:3px; }
.natloc-popup-name  { font-size:12px; color:var(--text-secondary,#5C6470); margin-bottom:2px; }
.natloc-popup-addr  { font-size:12px; color:var(--ink,#1B2235); margin-bottom:2px; }
.natloc-popup-cat   { font-size:11px; color:var(--text-secondary,#5C6470); text-transform:capitalize; }
.natloc-owner-result { margin-top:8px; }
.natloc-owner-name  { font-size:12.5px; font-weight:600; color:var(--ink,#1B2235); margin-bottom:2px; }
.natloc-owner-sub   { font-size:11px; color:var(--text-secondary,#5C6470); margin-bottom:4px; }
.natloc-empty       { font-size:11.5px; color:var(--text-secondary,#5C6470); }
    `;
    document.head.appendChild(s);
  }

  // ── Init ─────────────────────────────────────────────────────────────────
  function init(map) {
    _injectStyles();
    if (_map && _map !== map) {
      _map.off('moveend', _onMoveEnd);
      _map.off('zoomend', _onMoveEnd);
      _clear();
      if (_panel) { _panel.remove(); _panel = null; }
      _visible = false; _boundsKey = null;
    }
    _map = map;

    // Bind map events BEFORE building the panel — if _buildPanel() throws for
    // any reason (BrokerSegments not ready, template error, etc.) the fetch
    // loop still works once the master toggle is checked via the fallback toggle().
    map.on('moveend', _onMoveEnd);
    map.on('zoomend', _onMoveEnd);

    try {
      _buildPanel();
    } catch (e) {
      // Panel failed; inject a minimal fallback toggle button so the layer is
      // still usable without the full segment UI.
      const btn = document.createElement('button');
      btn.className = 'natloc-toggle-btn';
      btn.textContent = '🛍 Nearby';
      btn.onclick = toggle;
      map.getContainer().appendChild(btn);
      _panel = btn;
    }
  }

  function _onMoveEnd() { if (_visible) _refresh(); }

  // Exposed so the fallback button (and external callers) can toggle the layer.
  function toggle() {
    _visible = !_visible;
    const master = document.getElementById('natloc-master');
    if (master) master.checked = _visible;
    if (_visible) { _boundsKey = null; _refresh(); }
    else {
      _clear();
      _nameFilter = '';
      const si = document.getElementById('natloc-search');
      if (si) si.value = '';
    }
    _updateLegend();
  }

  // ── Panel ─────────────────────────────────────────────────────────────────
  function _buildPanel() {
    const segs = BrokerSegments.SEGMENTS;
    const tops = BrokerSegments.TOP_LABELS;

    // Group segments by top
    const byTop = {};
    segs.forEach(s => {
      (byTop[s.top] = byTop[s.top] || []).push(s);
    });

    const panel = document.createElement('div');
    panel.className = 'natloc-panel';
    panel.innerHTML = `
      <div class="natloc-panel-header" onclick="NatLocs._togglePanel()">
        <div class="natloc-panel-title">🛍 Nearby Retailers</div>
        <button class="natloc-panel-collapse" id="natloc-collapse-arrow">▾</button>
      </div>
      <div class="natloc-panel-body" id="natloc-panel-body">
        <div class="natloc-search-row">
          <input type="text" id="natloc-search" class="natloc-search-input"
                 placeholder="Search brand or category…" autocomplete="off">
        </div>
        <div class="natloc-master-row">
          <label>
            <input type="checkbox" id="natloc-master">
            <span>Show retail layer</span>
          </label>
        </div>
        ${Object.entries(tops).map(([topId, meta]) => {
          const groupSegs = byTop[topId] || [];
          return `
          <div class="natloc-group" data-top="${topId}">
            <div class="natloc-group-header">
              <input type="checkbox" class="natloc-top-cb" data-top="${topId}" checked>
              <span>${meta.icon} ${meta.label}</span>
            </div>
            <div class="natloc-segs" id="natloc-segs-${topId}">
              ${groupSegs.map(seg => `
              <div class="natloc-seg-row">
                <label>
                  <input type="checkbox" class="natloc-seg-cb" data-seg="${seg.id}" data-top="${topId}">
                  <span>${seg.icon} ${seg.label}</span>
                </label>
              </div>`).join('')}
              <div class="natloc-seg-row">
                <label>
                  <input type="checkbox" class="natloc-seg-cb" data-seg="other_${topId}" data-top="${topId}">
                  <span>📍 Other</span>
                </label>
              </div>
            </div>
          </div>`;
        }).join('')}
        <div class="natloc-legend" id="natloc-legend">
          <div>Active: all categories</div>
          <div class="natloc-legend-note">Recognized brands show logos</div>
        </div>
      </div>`;

    _map.getContainer().appendChild(panel);
    _panel = panel;

    // Search box — debounced 200ms, client-side only (no refetch)
    let _searchTimer = null;
    panel.querySelector('#natloc-search').addEventListener('input', e => {
      clearTimeout(_searchTimer);
      _searchTimer = setTimeout(() => {
        _nameFilter = e.target.value.trim();
        _applyFilter();
        _updateLegend();
      }, 200);
    });

    // Master toggle — delegate to toggle() so the fallback button and the
    // panel checkbox always stay in sync.
    panel.querySelector('#natloc-master').addEventListener('change', () => toggle());

    // Tier-1 (top) toggles — clicking the row label area
    panel.querySelectorAll('.natloc-top-cb').forEach(cb => {
      cb.addEventListener('change', e => {
        const top = e.target.dataset.top;
        if (e.target.checked) _disabledTops.delete(top);
        else                   _disabledTops.add(top);
        // Dim tier-2 rows when top is disabled
        panel.querySelectorAll(`.natloc-seg-row`).forEach(row => {
          const rowCb = row.querySelector('input');
          if (rowCb && rowCb.dataset.top === top)
            row.classList.toggle('disabled', !e.target.checked);
        });
        _applyFilter();
        _updateLegend();
      });
    });

    // Tier-2 (segment) checkboxes — delegate via querySelectorAll
    panel.querySelectorAll('.natloc-seg-cb').forEach(cb => {
      cb.addEventListener('change', e => {
        const { seg, top } = e.target.dataset;
        if (!_segFilter[top]) _segFilter[top] = new Set();
        if (e.target.checked)
          _segFilter[top].add(seg);
        else
          _segFilter[top].delete(seg);
        // Empty set = selecting nothing = show all for this top
        if (_segFilter[top].size === 0) _segFilter[top] = null;
        _applyFilter();
        _updateLegend();
      });
    });
  }

  function _togglePanel() {
    _panelOpen = !_panelOpen;
    const body = document.getElementById('natloc-panel-body');
    const arrow = document.getElementById('natloc-collapse-arrow');
    if (body) body.classList.toggle('hidden', !_panelOpen);
    if (arrow) arrow.textContent = _panelOpen ? '▾' : '▸';
  }

  function _updateLegend() {
    const el = document.getElementById('natloc-legend');
    if (!el) return;
    const activeCount = BrokerSegments.SEGMENTS.filter(s =>
      !_disabledTops.has(s.top)).length;
    el.querySelector('div').textContent =
      _visible ? `Active: ${activeCount} segments` : 'Layer off';
  }

  // ── Visibility logic ──────────────────────────────────────────────────────
  function _isVisible(loc) {
    const top = loc.category_top;
    if (!top || _disabledTops.has(top)) return false;

    const seg = BrokerSegments.segmentForLeaf(loc.category_primary, top);
    const filter = _segFilter[top];
    if (filter && filter.size > 0 && !filter.has(seg)) return false;

    if (_nameFilter) {
      const q = _nameFilter.toLowerCase();
      const segObj = BrokerSegments.SEGMENTS.find(s => s.id === seg);
      const matches =
        (loc.name_primary     || '').toLowerCase().includes(q) ||
        (loc.brand_primary    || '').toLowerCase().includes(q) ||
        (top).replace(/_/g, ' ').includes(q) ||
        (loc.category_primary || '').replace(/_/g, ' ').includes(q) ||
        (segObj ? segObj.label.toLowerCase().includes(q) : false) ||
        seg.replace(/_/g, ' ').includes(q);
      if (!matches) return false;
    }

    return true;
  }

  // ── Fetch + render ────────────────────────────────────────────────────────
  async function _refresh() {
    if (!_map || !_visible) return;
    const b = _map.getBounds();
    const key = [
      b.getSouth().toFixed(4), b.getWest().toFixed(4),
      b.getNorth().toFixed(4), b.getEast().toFixed(4),
    ].join(',');
    if (key === _boundsKey) return;
    _boundsKey = key;

    const params = new URLSearchParams({
      south: b.getSouth(), west: b.getWest(),
      north: b.getNorth(), east: b.getEast(),
      limit: 200,
    });

    try {
      const data = await API.get(`/national-locations/in-bbox?${params}`);
      _clear(false);
      const amber = getComputedStyle(document.documentElement)
                      .getPropertyValue('--dataviz-amber').trim() || '#A8702E';
      (data.items || []).forEach(loc => {
        if (loc.lat == null || loc.lng == null) return;
        const marker = L.marker([loc.lat, loc.lng], {
          icon: _buildIcon(loc, amber),
          zIndexOffset: -100,
        });
        marker.bindPopup(() => _makePopup(loc), { maxWidth: 280, minWidth: 180 });
        if (_isVisible(loc)) marker.addTo(_map);
        _markerData.push({ marker, loc });
      });
    } catch (_e) {
      // Non-fatal — main map still works.
    }
  }

  // ── Icon builder ──────────────────────────────────────────────────────────
  function _buildIcon(loc, amber) {
    const emoji = CATEGORY_EMOJI[loc.category_top] || FALLBACK_EMOJI;
    if (loc.website) {
      // Logo marker — rounded white chip; emoji on img load error
      const logoUrl = `https://img.logo.dev/${_esc(loc.website)}?size=40`;
      return L.divIcon({
        className: 'leaflet-div-icon',
        html: `<div class="natloc-logo-chip">
                 <img src="${logoUrl}"
                      alt=""
                      onerror="this.parentElement.innerHTML='<span style=\\'font-size:17px\\'>${emoji}</span>';this.onerror=null">
               </div>`,
        iconSize: [40, 40], iconAnchor: [20, 20],
      });
    }
    return L.divIcon({
      className: 'leaflet-div-icon',
      html: `<div class="natloc-dot" style="background:${amber}">${emoji}</div>`,
      iconSize: [40, 40], iconAnchor: [20, 20],
    });
  }

  // ── Client-side filter (no refetch) ──────────────────────────────────────
  function _applyFilter() {
    _markerData.forEach(({ marker, loc }) => {
      if (_isVisible(loc)) marker.addTo(_map);
      else marker.remove();
    });
  }

  // ── Popup ─────────────────────────────────────────────────────────────────
  function _makePopup(loc) {
    const container = document.createElement('div');
    container.className = 'natloc-popup';
    const brand = _esc(loc.brand_primary || loc.name_primary || '—');
    const name  = (loc.name_primary && loc.name_primary !== loc.brand_primary)
                    ? `<div class="natloc-popup-name">${_esc(loc.name_primary)}</div>` : '';
    const cat   = (loc.category_top || '').replace(/_/g, ' ');
    container.innerHTML = `
      <div class="natloc-popup-brand">${brand}</div>
      ${name}
      <div class="natloc-popup-addr">${_esc(loc.address || '—')}</div>
      <div class="natloc-popup-cat">${_esc(cat)}</div>`;

    const findBtn = document.createElement('button');
    findBtn.className = 'btn btn-outline btn-sm';
    findBtn.style.cssText = 'width:100%;margin-top:8px';
    findBtn.textContent = 'Find owner via public records';
    findBtn.onclick = () => findOwner(loc.id, findBtn);
    container.appendChild(findBtn);

    const resultDiv = document.createElement('div');
    resultDiv.className = 'natloc-owner-result';
    container.appendChild(resultDiv);
    findBtn._resultEl = resultDiv;

    return container;
  }

  // ── Clear ─────────────────────────────────────────────────────────────────
  function _clear(resetBoundsKey = true) {
    _markerData.forEach(({ marker }) => marker.remove());
    _markerData = [];
    if (resetBoundsKey) _boundsKey = null;
  }

  // ── Owner lookup ──────────────────────────────────────────────────────────
  async function findOwner(locationId, btnEl) {
    if (btnEl._loading) return;
    btnEl._loading = true;
    const origText = btnEl.textContent;
    btnEl.disabled = true;
    btnEl.textContent = 'Looking up…';

    let resultEl = btnEl._resultEl;
    if (!resultEl) {
      resultEl = document.createElement('div');
      resultEl.className = 'natloc-owner-result';
      btnEl.parentNode.insertBefore(resultEl, btnEl.nextSibling);
      btnEl._resultEl = resultEl;
    }
    try {
      const r = await API.post(`/national-locations/${locationId}/lookup-owner`, {});
      btnEl.style.display = 'none';
      resultEl.innerHTML = _ownerHtml(r, locationId);
    } catch (e) {
      btnEl._loading = false;
      btnEl.disabled = false;
      btnEl.textContent = origText;
      resultEl.innerHTML = `<div style="color:var(--red,#c0392b);font-size:12px">${_esc(e.message)}</div>`;
    }
  }

  function _ownerHtml(result, locationId) {
    if (!result.found) {
      return `<div class="natloc-empty">
        No public record found for this address.<br>
        <span style="font-size:11px">County parcel data may not be ingested yet.</span>
      </div>`;
    }
    if (result.account_id) {
      return `<div>
        <div class="natloc-owner-name">${_esc(result.account_name || '—')}</div>
        <div class="natloc-owner-sub" style="color:var(--accent,#1F5E52)">✓ Already in your book</div>
        <a href="/pages/account.html?id=${result.account_id}"
           class="btn btn-outline btn-sm"
           style="display:block;text-align:center;margin-top:6px"
           onclick="event.stopPropagation()">View account →</a>
      </div>`;
    }
    return `<div>
      <div class="natloc-owner-name">${_esc(result.owner_raw || '—')}</div>
      <div class="natloc-owner-sub">${_esc(result.parcel_address || '')}</div>
      <button class="btn btn-primary btn-sm"
              style="width:100%;margin-top:6px"
              onclick="NatLocs.createAccount(${result.parcel_regrid_id}, ${locationId}, this)">
        Add as account
      </button>
    </div>`;
  }

  async function createAccount(parcelRegridId, locationId, btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = 'Creating…';
    const resultEl = btnEl.closest('div');
    try {
      const r = await API.post(
        `/national-locations/${locationId}/create-account-from-parcel`,
        { parcel_regrid_id: parcelRegridId },
      );
      resultEl.innerHTML = `
        <div class="natloc-owner-name">${_esc(r.account_name || '—')}</div>
        <div class="natloc-owner-sub" style="color:var(--accent,#1F5E52)">✓ Account created</div>
        <a href="/pages/account.html?id=${r.account_id}"
           class="btn btn-outline btn-sm"
           style="display:block;text-align:center;margin-top:6px"
           onclick="event.stopPropagation()">View account →</a>`;
    } catch (e) {
      btnEl.disabled = false;
      btnEl.textContent = 'Add as account';
      resultEl.insertAdjacentHTML('beforeend',
        `<div style="color:var(--red,#c0392b);font-size:12px;margin-top:4px">${_esc(e.message)}</div>`);
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function _esc(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  return { init, toggle, _togglePanel, findOwner, createAccount };
})();
