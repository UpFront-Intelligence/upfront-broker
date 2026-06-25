// ── NatLocs — Overture Maps retail/restaurant map layer ──────────────────────
// Shared across every map surface in the app (Search, Property detail,
// Account/Contact mini-maps). Depends on Leaflet.js + API from app.js.
//
// Usage (any page with a Leaflet map):
//   1. <script src="/js/national_locations_layer.js?v=1">
//   2. After L.map(...) is ready: NatLocs.init(leafletMapInstance)
//      → auto-injects a toggle button into the map container
//
// The module is a singleton — fine because each page has exactly one map.

const NatLocs = (() => {
  // ── Category icons (emoji keyed by Overture taxonomy.hierarchy[1] value) ──
  // Keys are the EXACT strings written to national_locations.category_top
  // by scripts/ingest_overture_michigan.py — do not normalise or alter case.
  const CATEGORY_EMOJI = {
    food_and_drink:             '🍽️',
    shopping:                   '🛍️',
    travel_and_transportation:  '✈️',
    lifestyle_services:         '💈',
    services_and_business:      '🏢',
  };
  const FALLBACK_EMOJI = '📍';

  // ── State ────────────────────────────────────────────────────────────────
  let _map     = null;
  let _markers = [];
  let _visible = false;
  let _toggleBtn = null;
  let _boundsKey = null;   // debounce: skip refresh when bounds unchanged
  let _styleInjected = false;

  // ── CSS (injected once into <head> on first init) ────────────────────────
  function _injectStyles() {
    if (_styleInjected) return;
    _styleInjected = true;
    const style = document.createElement('style');
    style.textContent = `
.natloc-toggle-btn {
  position: absolute; bottom: 30px; left: 10px; z-index: 500;
  background: var(--surface, #fff); border: 1px solid var(--border, rgba(27,34,53,0.08));
  border-radius: var(--radius-sm, 8px); padding: 5px 9px;
  font-size: 11.5px; cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,0.15);
  font-family: var(--font-system, -apple-system, sans-serif);
  color: var(--text-secondary, #5C6470); user-select: none;
  transition: background 0.15s;
}
.natloc-toggle-btn.active {
  background: var(--dataviz-amber-soft, #F2E2D0);
  color: var(--dataviz-amber, #A8702E); border-color: var(--dataviz-amber, #A8702E);
}
.natloc-toggle-btn:hover { background: var(--paper, #F3F2EE); }
.natloc-toggle-btn.active:hover { background: var(--dataviz-amber-soft, #F2E2D0); }

.natloc-dot {
  width: 22px; height: 22px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; border: 2px solid #fff;
  box-shadow: 0 1px 3px rgba(0,0,0,0.25); cursor: pointer;
}
.leaflet-div-icon { background: none; border: none; }

.natloc-popup { min-width: 180px; font-family: var(--font-system, -apple-system, sans-serif); }
.natloc-popup-brand { font-size: 13.5px; font-weight: 600; color: var(--ink, #1B2235); margin-bottom: 3px; }
.natloc-popup-name  { font-size: 12px; color: var(--text-secondary, #5C6470); margin-bottom: 2px; }
.natloc-popup-addr  { font-size: 12px; color: var(--ink, #1B2235); margin-bottom: 2px; }
.natloc-popup-cat   { font-size: 11px; color: var(--text-secondary, #5C6470); text-transform: capitalize; }
.natloc-owner-result { margin-top: 8px; }
.natloc-owner-name  { font-size: 12.5px; font-weight: 600; color: var(--ink, #1B2235); margin-bottom: 2px; }
.natloc-owner-sub   { font-size: 11px; color: var(--text-secondary, #5C6470); margin-bottom: 4px; }
.natloc-empty       { font-size: 11.5px; color: var(--text-secondary, #5C6470); }
    `;
    document.head.appendChild(style);
  }

  // ── Init ─────────────────────────────────────────────────────────────────
  function init(map) {
    _injectStyles();

    // Detach from any previous map instance (in case the same page
    // reconstructs its map, e.g. account/contact detail lazy init)
    if (_map && _map !== map) {
      _map.off('moveend', _onMoveEnd);
      _clear();
      _toggleBtn && _toggleBtn.remove();
      _toggleBtn = null;
      _visible = false;
      _boundsKey = null;
    }

    _map = map;

    // Inject toggle button directly into the Leaflet map container
    // (same technique Leaflet's own controls use — position: absolute
    // inside the map container which is position: relative).
    const btn = document.createElement('button');
    btn.className = 'natloc-toggle-btn';
    btn.title = 'Toggle retail / restaurant overlay';
    btn.textContent = '🛍 Nearby';
    btn.onclick = toggle;
    map.getContainer().appendChild(btn);
    _toggleBtn = btn;

    map.on('moveend', _onMoveEnd);
  }

  function _onMoveEnd() {
    if (_visible) _refresh();
  }

  function toggle() {
    _visible = !_visible;
    _toggleBtn && _toggleBtn.classList.toggle('active', _visible);
    if (_visible) {
      _boundsKey = null;   // force a fresh load on show
      _refresh();
    } else {
      _clear();
    }
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
      _clear(false);  // clear markers but keep boundsKey
      const amber = getComputedStyle(document.documentElement)
                      .getPropertyValue('--dataviz-amber').trim() || '#A8702E';
      (data.items || []).forEach(loc => {
        if (loc.lat == null || loc.lng == null) return;
        const emoji = CATEGORY_EMOJI[loc.category_top] || FALLBACK_EMOJI;
        const icon = L.divIcon({
          className: 'leaflet-div-icon',
          html: `<div class="natloc-dot" style="background:${amber}" data-cat="${loc.category_top || ''}">${emoji}</div>`,
          iconSize: [22, 22], iconAnchor: [11, 11],
        });
        const marker = L.marker([loc.lat, loc.lng], { icon, zIndexOffset: -100 });
        marker.bindPopup(() => _makePopup(loc), { maxWidth: 280, minWidth: 180 });
        marker.addTo(_map);
        _markers.push(marker);
      });
    } catch (e) {
      // Non-fatal — silently suppress; the main map view still works.
      // Likely causes: auth expired, DB unreachable, network issue.
    }
  }

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

  function _clear(resetBoundsKey = true) {
    _markers.forEach(m => m.remove());
    _markers = [];
    if (resetBoundsKey) _boundsKey = null;
  }

  // ── Owner lookup (shared between popup and search table) ─────────────────
  async function findOwner(locationId, btnEl) {
    if (btnEl._loading) return;
    btnEl._loading = true;
    const origText = btnEl.textContent;
    btnEl.disabled = true;
    btnEl.textContent = 'Looking up…';

    // Result container: use the pre-linked _resultEl (set by _makePopup for
    // popups) or create one adjacent to the button (for search table cells).
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
    // Parcel found, no matched account — offer "Add as account"
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
      resultEl.insertAdjacentHTML(
        'beforeend',
        `<div style="color:var(--red,#c0392b);font-size:12px;margin-top:4px">${_esc(e.message)}</div>`,
      );
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function _esc(s) {
    return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  return { init, toggle, findOwner, createAccount };
})();
