// ── UpFront Broker — Shared Utilities ──────────────────────────

const API = (() => {
  const BASE = '';  // same origin

  function token() {
    return localStorage.getItem('ufb_token');
  }

  function headers() {
    const h = { 'Content-Type': 'application/json' };
    if (token()) h['Authorization'] = `Bearer ${token()}`;
    return h;
  }

  async function request(method, path, body) {
    const opts = { method, headers: headers() };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(`/api${path}`, opts);
    if (res.status === 401) {
      Auth.logout();
      return null;
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Request failed' }));
      throw new Error(err.detail || 'Request failed');
    }
    return res.json();
  }

  return {
    get:    (path)        => request('GET',    path),
    post:   (path, body)  => request('POST',   path, body),
    put:    (path, body)  => request('PUT',    path, body),
    delete: (path)        => request('DELETE', path),
    token,
  };
})();

// ── Auth ────────────────────────────────────────────────────────
const Auth = (() => {
  let _user = null;

  function user() {
    if (_user) return _user;
    const stored = localStorage.getItem('ufb_user');
    if (stored) { try { _user = JSON.parse(stored); } catch(e) {} }
    return _user;
  }

  function setUser(u) {
    _user = u;
    localStorage.setItem('ufb_user', JSON.stringify(u));
  }

  function logout() {
    localStorage.removeItem('ufb_token');
    localStorage.removeItem('ufb_user');
    _user = null;
    window.location.href = '/pages/login.html';
  }

  function requireAuth() {
    if (!API.token()) {
      window.location.href = '/pages/login.html';
      return false;
    }
    return true;
  }

  function initials(u) {
    u = u || user();
    if (!u) return '?';
    const parts = (u.full_name || u.email || '').split(' ');
    return parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : (parts[0] || '?')[0].toUpperCase();
  }

  return { user, setUser, logout, requireAuth, initials };
})();

// ── Toast ────────────────────────────────────────────────────────
const Toast = (() => {
  function show(msg, type = 'info', duration = 3500) {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      document.body.appendChild(container);
    }
    const icons = { success: '✓', error: '✕', info: '●' };
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.innerHTML = `<span>${icons[type] || '●'}</span><span>${msg}</span>`;
    container.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transition = 'opacity 0.3s';
      setTimeout(() => el.remove(), 300);
    }, duration);
  }

  return {
    success: (msg) => show(msg, 'success'),
    error:   (msg) => show(msg, 'error'),
    info:    (msg) => show(msg, 'info'),
  };
})();

// ── Format Utilities ─────────────────────────────────────────────
const Fmt = (() => {
  const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
  const number   = new Intl.NumberFormat('en-US');

  return {
    currency: (v) => v != null ? currency.format(v) : '—',
    number:   (v) => v != null ? number.format(v)   : '—',
    sf:       (v) => v != null ? `${number.format(v)} SF` : '—',
    pct:      (v) => v != null ? `${v}%`            : '—',
    date:     (v) => v ? new Date(v).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—',
    dateShort:(v) => v ? new Date(v).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—',
    initials: (firstName, lastName) => {
      const f = (firstName || '')[0] || '';
      const l = (lastName  || '')[0] || '';
      return (f + l).toUpperCase() || '?';
    },
    propType: (type) => {
      const icons = {
        'Office': '🏢', 'Industrial': '🏭', 'Retail': '🏪',
        'Land': '🌿', 'Multifamily': '🏘️', 'STNL': '🏬',
        'Self Storage': '📦', 'Hospitality': '🏨', 'Medical': '🏥'
      };
      return icons[type] || '🏗️';
    },
    stageClass: (stage) => 'stage-' + (stage || 'Prospecting').replace(/\s+/g, '-'),
  };
})();

// ── Modal Helper ─────────────────────────────────────────────────
const Modal = (() => {
  function open(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add('open');
  }
  function close(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('open');
  }
  function closeOnOverlay(id) {
    const el = document.getElementById(id);
    if (el) el.addEventListener('click', (e) => { if (e.target === el) close(id); });
  }
  return { open, close, closeOnOverlay };
})();

// ── Sidebar Active State ─────────────────────────────────────────
function setActiveNav(page) {
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.page === page);
  });
}

// ── Avatar Color Seeds ───────────────────────────────────────────
function avatarColor(str) {
  const colors = [
    '#2d4a7a','#4a2d7a','#2d7a4a','#7a4a2d',
    '#2d7a7a','#7a2d4a','#4a7a2d','#7a2d2d',
  ];
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  return colors[Math.abs(hash) % colors.length];
}

// ── Sidebar Renderer ─────────────────────────────────────────────
function renderSidebar(activePage) {
  const user = Auth.user();
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;

  sidebar.innerHTML = `
    <div class="sidebar-brand">
      <div class="brand-wordmark">
        <span class="brand-upfront">UpFront</span>
        <span class="brand-broker">&nbsp;Broker</span>
      </div>
      <div class="brand-tagline">Commercial Real Estate Intelligence</div>
    </div>

    <nav class="sidebar-nav">
      <div class="nav-section">
        <div class="nav-section-label">Workspace</div>
        <div class="nav-item ${activePage==='dashboard'?'active':''}" data-page="dashboard" onclick="navigate('dashboard')">
          <span class="nav-icon">⬡</span> Dashboard
        </div>
        <div class="nav-item ${activePage==='pipeline'?'active':''}" data-page="pipeline" onclick="navigate('pipeline')">
          <span class="nav-icon">◈</span> Pipeline
        </div>
        <div class="nav-item ${activePage==='marketing-lists'?'active':''}" data-page="marketing-lists" onclick="navigate('marketing-lists')">
          <span class="nav-icon">◈</span> Lists
        </div>
        <div class="nav-item ${activePage==='query'?'active':''}" data-page="query" onclick="navigate('query')">
          <span class="nav-icon">⊗</span> Query
        </div>
      </div>

      <div class="nav-section">
        <div class="nav-section-label">Records</div>
        <div class="nav-item ${activePage==='properties'?'active':''}" data-page="properties" onclick="navigate('properties')">
          <span class="nav-icon">⌂</span> Properties
        </div>
        <div class="nav-item ${activePage==='contacts'?'active':''}" data-page="contacts" onclick="navigate('contacts')">
          <span class="nav-icon">◎</span> Contacts
        </div>
        <div class="nav-item ${activePage==='accounts'?'active':''}" data-page="accounts" onclick="navigate('accounts')">
          <span class="nav-icon">◻</span> Accounts
        </div>
        <div class="nav-item ${activePage==='tenants'?'active':''}" data-page="tenants" onclick="navigate('tenants')">
          <span class="nav-icon">⬡</span> Tenants
        </div>
        <div class="nav-item ${activePage==='deals'?'active':''}" data-page="deals" onclick="navigate('deals')">
          <span class="nav-icon">◆</span> Deals
        </div>
      </div>

      <div class="nav-section">
        <div class="nav-section-label">Tools</div>
        <div class="nav-item ${activePage==='comps'?'active':''}" data-page="comps" onclick="navigate('comps')">
          <span class="nav-icon">≡</span> Comps
        </div>
        <div class="nav-item ${activePage==='import'?'active':''}" data-page="import" onclick="navigate('import')">
          <span class="nav-icon">⇪</span> Import
        </div>
        <div class="nav-item ${activePage==='finder'?'active':''}" data-page="finder" onclick="navigate('finder')">
          <span class="nav-icon">⊙</span> Property Finder
        </div>
        <div class="nav-item ${activePage==='portfolio'?'active':''}" data-page="portfolio" onclick="navigate('portfolio')">
          <span class="nav-icon">◈</span> Portfolio Intel
        </div>
        <div class="nav-item ${activePage==='portal'?'active':''}" data-page="portal" onclick="navigate('portal')">
          <span class="nav-icon">⊕</span> Client Portal
        </div>
      </div>
    </nav>

    <div class="sidebar-footer">
      <div class="sidebar-user">
        <div class="user-avatar" style="background:${user ? avatarColor(user.email) : '#333'}">
          ${user && user.photo_url ? `<img src="${user.photo_url}" alt="">` : (user ? Auth.initials(user) : '?')}
        </div>
        <div class="user-info">
          <div class="user-name">${user ? (user.full_name || user.email) : 'Loading...'}</div>
          <div class="user-company">${user ? (user.company || 'UpFront Broker') : ''}</div>
        </div>
        <button class="btn btn-ghost" style="padding:4px;color:var(--stone)" title="Sign out" onclick="Auth.logout()">↪</button>
      </div>
    </div>
  `;
}

// ── Shared clip-proof typeahead ──────────────────────────────────
// Renders to document.body with position:fixed so no ancestor overflow
// (rounded-corner cards, modal scrollbodies, overflow:hidden containers)
// can ever clip the results list.
const Typeahead = (() => {
  let _el = null;
  let _fns = [];

  function _pos(anchor) {
    if (!_el) return;
    const r = anchor.getBoundingClientRect();
    _el.style.top   = (r.bottom + 2) + 'px';
    _el.style.left  = r.left + 'px';
    _el.style.width = Math.max(r.width, 200) + 'px';
  }

  function close() {
    if (_el) { _el.remove(); _el = null; }
    _fns.forEach(f => f());
    _fns = [];
  }

  // open(anchor, items, onSelect)
  // item shape: {label, meta?, html?, value?}
  //   label — display text (used when html is absent)
  //   meta  — small badge rendered before label
  //   html  — raw innerHTML for the row (skips label/meta rendering)
  //   value — passed back to onSelect unchanged
  function open(anchor, items, onSelect) {
    close();
    if (!items || !items.length) return;

    _el = document.createElement('div');
    _el.className = 'ta-float';
    document.body.appendChild(_el);
    _pos(anchor);

    items.forEach(item => {
      const row = document.createElement('div');
      if (item.html) {
        row.innerHTML = item.html;
      } else {
        row.className = 'ta-float-row';
        if (item.meta != null && item.meta !== '') {
          const m = document.createElement('span');
          m.className = 'ta-float-meta';
          m.textContent = item.meta;
          row.appendChild(m);
        }
        const txt = document.createElement('span');
        txt.textContent = item.label;
        row.appendChild(txt);
      }
      row.addEventListener('mousedown', e => { e.preventDefault(); onSelect(item); close(); });
      _el.appendChild(row);
    });

    const reposition = () => _pos(anchor);
    const outside    = e => { if (_el && !_el.contains(e.target) && e.target !== anchor) close(); };
    window.addEventListener('scroll', reposition, true);
    window.addEventListener('resize', reposition);
    document.addEventListener('mousedown', outside);
    _fns = [
      () => window.removeEventListener('scroll', reposition, true),
      () => window.removeEventListener('resize', reposition),
      () => document.removeEventListener('mousedown', outside),
    ];
  }

  // attach(input, fetchFn, onSelect, opts?)
  // Wires input events.  fetchFn(q) must return Promise<item[]>.
  // Caller's onSelect(item, input) receives the item and the input element.
  function attach(input, fetchFn, onSelect, opts = {}) {
    const delay  = opts.delay  ?? 220;
    const minLen = opts.minLen ?? 2;
    let timer = null;
    input.addEventListener('input', () => {
      clearTimeout(timer);
      close();
      const q = input.value.trim();
      if (q.length < minLen) return;
      timer = setTimeout(async () => {
        const items = await fetchFn(q).catch(() => []);
        open(input, items, item => onSelect(item, input));
      }, delay);
    });
    input.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    input.addEventListener('blur',    () => setTimeout(() => { if (_el) close(); }, 150));
  }

  return { open, close, attach };
})();

// ── SPA Navigation ───────────────────────────────────────────────
function navigate(page) {
  window.location.href = `/pages/${page}.html`;
}
