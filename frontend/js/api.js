const API_BASE = "/api";

// Safari private-browsing mode (and some locked-down browser settings) can
// throw on any localStorage access instead of just failing quietly, which
// used to break every page — including login — with an uncaught exception
// and a blank screen. These wrappers fail safe instead.
function safeStorageGet(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}
function safeStorageSet(key, value) {
  try { localStorage.setItem(key, value); return true; } catch (e) { return false; }
}
function safeStorageRemove(key) {
  try { localStorage.removeItem(key); } catch (e) { /* nothing to do */ }
}

function getToken() {
  return safeStorageGet("rc_token");
}

function getUser() {
  const raw = safeStorageGet("rc_user");
  if (!raw) return null;
  try { return JSON.parse(raw); } catch (e) { return null; }
}

function setSession(token, user) {
  safeStorageSet("rc_token", token);
  safeStorageSet("rc_user", JSON.stringify(user));
}

function clearSession() {
  safeStorageRemove("rc_token");
  safeStorageRemove("rc_user");
}

function requireAuth() {
  if (!getToken()) {
    window.location.href = "login.html";
  }
}

function requireRole(...roles) {
  const user = getUser();
  if (!user || !roles.includes(user.role)) {
    window.location.href = "dashboard.html";
  }
}

async function api(path, options = {}) {
  const headers = options.headers || {};
  headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    clearSession();
    window.location.href = "login.html";
    return null;
  }
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }
  if (!res.ok) {
    const message = (data && data.detail) ? data.detail : "Something went wrong. Please try again.";
    throw new Error(message);
  }
  return data;
}

// Like api(), but for multipart/form-data (file uploads). Never set
// Content-Type manually here — the browser needs to add its own boundary.
async function apiUpload(path, formData, method = "POST") {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { method, headers, body: formData });
  if (res.status === 401) {
    clearSession();
    window.location.href = "login.html";
    return null;
  }
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }
  if (!res.ok) {
    const message = (data && data.detail) ? data.detail : "Something went wrong. Please try again.";
    throw new Error(message);
  }
  return data;
}

function initials(name) {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function timeAgo(dateStr) {
  const date = new Date(dateStr + (dateStr.endsWith("Z") ? "" : "Z"));
  const seconds = Math.floor((new Date() - date) / 1000);
  const units = [
    ["year", 31536000], ["month", 2592000], ["day", 86400],
    ["hour", 3600], ["minute", 60],
  ];
  for (const [label, secs] of units) {
    const val = Math.floor(seconds / secs);
    if (val >= 1) return `${val} ${label}${val > 1 ? "s" : ""} ago`;
  }
  return "just now";
}

function renderNav(activePage) {
  const user = getUser();
  const navEl = document.getElementById("rc-nav");
  if (!navEl) return;

  const links = [
    { href: "dashboard.html", label: "Dashboard", key: "dashboard" },
    { href: "library.html", label: "Library", key: "library" },
    { href: "community.html", label: "Community", key: "community" },
  ];
  const myReadingLinks = [
    { href: "journal.html", label: "Journal", key: "journal" },
    { href: "progress.html", label: "My Progress", key: "progress" },
    { href: "shelves.html", label: "My Shelves", key: "shelves" },
  ];
  const moreLinks = [
    { href: "upload.html", label: "Upload a Book", key: "upload" },
    { href: "clubs.html", label: "Reading Clubs", key: "clubs" },
    { href: "training-groups.html", label: "Training Groups", key: "training-groups" },
    { href: "mentors.html", label: "Mentors", key: "mentors" },
    { href: "live.html", label: "Live Discussions", key: "live" },
    { href: "resources.html", label: "Reading Resources", key: "resources" },
    { href: "opportunities.html", label: "Opportunities Hub", key: "opportunities" },
  ];
  if (user && (user.role === "admin" || user.role === "moderator")) {
    links.push({ href: "admin.html", label: "Admin", key: "admin" });
  }

  navEl.innerHTML = `
    <nav class="navbar navbar-expand-lg navbar-rc">
      <div class="container">
        <a class="navbar-brand" href="dashboard.html"><img src="img/logo.png" alt="Gwin's Readers Club" class="navbar-logo-img">Gwin's Readers Club</a>
        <form class="d-none d-lg-flex mx-3" style="width:220px;" onsubmit="event.preventDefault(); doNavSearch();">
          <input type="text" id="nav-search-input" class="form-control form-control-sm" placeholder="Search everything...">
        </form>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#rcNavContent">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="rcNavContent">
          <ul class="navbar-nav me-auto">
            ${links.map(l => `<li class="nav-item"><a class="nav-link ${activePage === l.key ? "active" : ""}" href="${l.href}">${l.label}</a></li>`).join("")}
            <li class="nav-item dropdown">
              <a class="nav-link dropdown-toggle ${myReadingLinks.some(l => l.key === activePage) ? "active" : ""}" href="#" role="button" data-bs-toggle="dropdown">My Reading</a>
              <ul class="dropdown-menu">
                ${myReadingLinks.map(l => `<li><a class="dropdown-item" href="${l.href}">${l.label}</a></li>`).join("")}
              </ul>
            </li>
            <li class="nav-item dropdown">
              <a class="nav-link dropdown-toggle ${moreLinks.some(l => l.key === activePage) ? "active" : ""}" href="#" role="button" data-bs-toggle="dropdown">More</a>
              <ul class="dropdown-menu">
                ${moreLinks.map(l => `<li><a class="dropdown-item" href="${l.href}">${l.label}</a></li>`).join("")}
              </ul>
            </li>
          </ul>
          <ul class="navbar-nav align-items-lg-center">
            <li class="nav-item d-lg-none px-2">
              <input type="text" id="nav-search-input-mobile" class="form-control form-control-sm my-2" placeholder="Search everything..." onkeydown="if(event.key==='Enter'){document.getElementById('nav-search-input').value=this.value; doNavSearch();}">
            </li>
            <li class="nav-item me-lg-2 px-2 px-lg-0">
              <a href="donate.html" class="btn btn-rc-gold btn-sm w-100" style="white-space:nowrap;">💛 Donate</a>
            </li>
            <li class="nav-item">
              <a class="nav-link" href="#" title="Toggle dark mode" onclick="event.preventDefault(); toggleAppDarkMode();">🌓</a>
            </li>
            <li class="nav-item">
              <a class="nav-link position-relative" href="messages.html" title="Messages">
                ✉️ <span id="unread-msg-dot"></span>
              </a>
            </li>
            <li class="nav-item">
              <a class="nav-link position-relative" href="notifications.html" title="Notifications">
                🔔 <span id="unread-dot"></span>
              </a>
            </li>
            <li class="nav-item dropdown">
              <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">
                ${user ? user.full_name : "Account"}
              </a>
              <ul class="dropdown-menu dropdown-menu-end">
                <li><a class="dropdown-item" href="profile.html">Profile & Settings</a></li>
                <li><hr class="dropdown-divider"></li>
                <li><a class="dropdown-item" href="#" onclick="logout()">Log out</a></li>
              </ul>
            </li>
          </ul>
        </div>
      </div>
    </nav>
  `;

  api("/notifications/unread-count").then(r => {
    if (r && r.unread > 0) {
      document.getElementById("unread-dot").innerHTML = `<span class="notif-dot"></span>`;
    }
  }).catch(() => {});

  api("/messages/unread-count").then(r => {
    if (r && r.unread > 0) {
      document.getElementById("unread-msg-dot").innerHTML = `<span class="notif-dot"></span>`;
    }
  }).catch(() => {});

  applyStoredDarkMode();
}

function doNavSearch() {
  const q = document.getElementById("nav-search-input").value.trim();
  if (q) window.location.href = `search.html?q=${encodeURIComponent(q)}`;
}

function toggleAppDarkMode() {
  const isDark = document.body.classList.toggle("app-dark-mode");
  safeStorageSet("rc_dark_mode", isDark ? "1" : "0");
}

function applyStoredDarkMode() {
  if (safeStorageGet("rc_dark_mode") === "1") {
    document.body.classList.add("app-dark-mode");
  }
}

// Register the service worker for offline app-shell caching (PWA).
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => { /* offline support is best-effort */ });
  });
}

// Renders the shared site footer (with social links) on any page that
// includes this script and doesn't already have its own .footer-rc.
function renderFooter() {
  if (document.querySelector(".footer-rc")) return;
  const footer = document.createElement("div");
  footer.className = "footer-rc text-center";
  footer.innerHTML = `
    <div class="container">
      <img src="img/logo.png" alt="Gwin's Readers Club" class="footer-logo-img">
      <div class="footer-social mb-3">
        <a href="https://www.facebook.com/profile.php?id=61592761046123" class="social-icon" aria-label="Facebook" target="_blank" rel="noopener">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M13.5 21v-8.06h2.7l.4-3.14h-3.1V7.86c0-.91.25-1.53 1.56-1.53h1.66V3.53C15.98 3.44 15 3.35 13.86 3.35c-2.4 0-4.04 1.47-4.04 4.16v2.45H7.1v3.14h2.72V21h3.68z"/></svg>
        </a>
        <a href="https://www.instagram.com/gwins_readers_club?igsh=MTEyaDAyb2NkbGw0MA==" class="social-icon" aria-label="Instagram" target="_blank" rel="noopener">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M12 8.4a3.6 3.6 0 1 0 0 7.2 3.6 3.6 0 0 0 0-7.2zm0 5.94a2.34 2.34 0 1 1 0-4.68 2.34 2.34 0 0 1 0 4.68zm4.6-6.1a.84.84 0 1 1-1.68 0 .84.84 0 0 1 1.68 0zM12 4.62c2.4 0 2.68.01 3.63.05.88.04 1.35.19 1.67.31.42.16.72.36 1.03.67.32.32.51.61.68 1.03.12.32.27.8.31 1.68.04.95.05 1.23.05 3.64s-.01 2.69-.05 3.64c-.04.88-.19 1.36-.31 1.68a2.8 2.8 0 0 1-.68 1.03c-.31.31-.61.51-1.03.67-.32.13-.79.28-1.67.32-.95.04-1.23.05-3.63.05s-2.69-.01-3.64-.05c-.88-.04-1.35-.19-1.67-.32a2.78 2.78 0 0 1-1.03-.67 2.8 2.8 0 0 1-.68-1.03c-.12-.32-.27-.8-.31-1.68-.04-.95-.05-1.23-.05-3.64s.01-2.69.05-3.64c.04-.88.19-1.36.31-1.68.17-.42.36-.71.68-1.03.31-.31.61-.51 1.03-.67.32-.12.79-.27 1.67-.31.95-.04 1.23-.05 3.64-.05zm0-1.62c-2.44 0-2.75.01-3.71.06-.96.04-1.62.2-2.19.42-.6.23-1.1.54-1.6 1.04-.5.5-.81 1-1.04 1.6-.23.57-.38 1.23-.42 2.19-.05.96-.06 1.27-.06 3.71s.01 2.75.06 3.71c.04.96.2 1.62.42 2.19.23.6.54 1.1 1.04 1.6.5.5 1 .81 1.6 1.04.57.22 1.23.38 2.19.42.96.05 1.27.06 3.71.06s2.75-.01 3.71-.06c.96-.04 1.62-.2 2.19-.42.6-.23 1.1-.54 1.6-1.04.5-.5.81-1 1.04-1.6.22-.57.38-1.23.42-2.19.05-.96.06-1.27.06-3.71s-.01-2.75-.06-3.71c-.04-.96-.2-1.62-.42-2.19a4.4 4.4 0 0 0-1.04-1.6 4.4 4.4 0 0 0-1.6-1.04c-.57-.22-1.23-.38-2.19-.42-.96-.05-1.27-.06-3.71-.06z"/></svg>
        </a>
        <a href="https://tiktok.com/@gwinsreadersclub" class="social-icon" aria-label="TikTok" target="_blank" rel="noopener">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M16.6 5.82c-.9-.87-1.46-2.07-1.46-3.42h-3.1v13.44c0 1.5-1.22 2.72-2.72 2.72a2.72 2.72 0 0 1-2.72-2.72 2.72 2.72 0 0 1 2.72-2.72c.28 0 .55.04.8.12v-3.15a5.86 5.86 0 0 0-.8-.06 5.82 5.82 0 0 0 0 11.64 5.82 5.82 0 0 0 5.82-5.83V9.4a7.5 7.5 0 0 0 4.4 1.4V7.7a4.36 4.36 0 0 1-2.94-1.88z"/></svg>
        </a>
        <a href="https://www.youtube.com/@Gwinsreadersclub" class="social-icon" aria-label="YouTube" target="_blank" rel="noopener">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M21.6 7.6a2.7 2.7 0 0 0-1.9-1.9C18 5.2 12 5.2 12 5.2s-6 0-7.7.5a2.7 2.7 0 0 0-1.9 1.9C2 9.3 2 12 2 12s0 2.7.5 4.4a2.7 2.7 0 0 0 1.9 1.9c1.7.5 7.7.5 7.7.5s6 0 7.7-.5a2.7 2.7 0 0 0 1.9-1.9c.5-1.7.5-4.4.5-4.4s0-2.7-.5-4.4zM10 15.2V8.8L15.5 12 10 15.2z"/></svg>
        </a>
        <a href="https://chat.whatsapp.com/Cog5deCm2Mz3nzjInpFXOs?s=cl&p=a&ilr=0&amv=0" class="social-icon" aria-label="WhatsApp Community" target="_blank" rel="noopener">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5.06-1.33A10 10 0 1 0 12 2zm0 18.2a8.17 8.17 0 0 1-4.17-1.14l-.3-.18-3 .79.8-2.93-.2-.3A8.2 8.2 0 1 1 12 20.2zm4.5-6.13c-.24-.12-1.45-.72-1.68-.8-.22-.08-.39-.12-.55.12-.16.24-.63.8-.78.96-.14.16-.29.18-.53.06-.24-.12-1.02-.38-1.94-1.2-.72-.64-1.2-1.43-1.35-1.67-.14-.24-.02-.37.11-.49.11-.11.24-.29.36-.43.12-.14.16-.24.24-.4.08-.16.04-.3-.02-.42-.06-.12-.55-1.32-.75-1.8-.2-.48-.4-.4-.55-.41h-.47c-.16 0-.42.06-.64.3-.22.24-.84.82-.84 2s.86 2.32.98 2.48c.12.16 1.7 2.6 4.12 3.64.58.25 1.03.4 1.38.51.58.18 1.11.16 1.53.1.47-.07 1.45-.59 1.65-1.16.2-.57.2-1.06.14-1.16-.06-.1-.22-.16-.46-.28z"/></svg>
        </a>
      </div>
      <div class="mb-3">
        <a href="donate.html" class="btn btn-rc-gold btn-sm px-4">💛 Donate to the Club</a>
      </div>
      <div class="mb-2">
        <a href="safety.html" class="link-light small me-3">🛟 Safety Center</a>
        <a href="privacy-policy.html" class="link-light small">Privacy &amp; Child Safety Policy</a>
      </div>
      <small>&copy; 2026 Gwin's Readers Club — Read. Reflect. Grow.</small>
    </div>
  `;
  document.body.appendChild(footer);
}
document.addEventListener("DOMContentLoaded", renderFooter);

function logout() {
  clearSession();
  window.location.href = "login.html";
}

// --- Idle auto-logout ---
// Shared/school devices are common among our members, so a signed-in session
// left unattended is a real risk. After 20 minutes of no clicks/keys/taps,
// sign out automatically rather than leaving someone else's account open.
const IDLE_LOGOUT_MS = 20 * 60 * 1000;
let _idleTimer = null;
function _resetIdleTimer() {
  if (!getToken()) return;
  if (_idleTimer) clearTimeout(_idleTimer);
  _idleTimer = setTimeout(() => {
    if (getToken()) {
      clearSession();
      window.location.href = "login.html?idle=1";
    }
  }, IDLE_LOGOUT_MS);
}
["click", "keydown", "touchstart", "scroll"].forEach((evt) => {
  document.addEventListener(evt, _resetIdleTimer, { passive: true });
});
_resetIdleTimer();

function showAlert(containerId, message, type = "danger") {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = `<div class="alert alert-${type} py-2">${message}</div>`;
}

/**
 * Renders a book cover as an <img> when the book has an uploaded cover
 * photo (book.cover_url), falling back to the coloured title-card
 * placeholder otherwise. `styleOverride` is a raw inline-style string
 * (e.g. "width:70px; min-width:70px; height:96px; font-size:0.7rem;")
 * applied to whichever element is rendered, so callers keep their sizing.
 */
function escapeHtml(str) {
  const d = document.createElement("div");
  d.innerText = str == null ? "" : String(str);
  return d.innerHTML;
}

function bookCoverHtml(book, styleOverride = "", titleSlice = null) {
  const title = titleSlice ? (book.title || "").slice(0, titleSlice) : (book.title || "");
  if (book && book.cover_url) {
    return `<img src="${book.cover_url}" alt="${escapeHtml(book.title || "")} cover" class="book-cover-photo" style="${styleOverride}" loading="lazy">`;
  }
  const bg = (book && book.cover_color) || "#35538F";
  return `<div class="book-cover" style="background:${bg}; ${styleOverride}">${escapeHtml(title)}</div>`;
}
