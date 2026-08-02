// v4: CSS/JS are no longer precached by their own bare names here. The
// frontend now links them with a cache-busting "?v=" query string, so the
// requests this worker actually sees for those files never match a
// precached "css/style.css" entry anyway — precaching it was dead weight
// at best. Worse, on a previous version a stale-cache fallback for those
// files could shadow a fresh, correctly-typed response with an old broken
// one. Bumping CACHE_NAME forces every browser with an old worker
// installed to drop its old cache outright (see the activate handler)
// instead of quietly continuing to serve whatever it happened to have
// cached from before any of these fixes existed.
const CACHE_NAME = "readersclub-shell-v4";
const SHELL_FILES = [
  "dashboard.html",
  "library.html",
  "book.html",
  "reader.html",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Never cache API calls — reading/writing live data always goes to the
  // network (or reader.html's own sync queue when that fails); an HTTP
  // cache here would serve stale progress/highlights with no way to
  // reconcile them later.
  if (url.pathname.startsWith("/api/")) return;
  if (event.request.method !== "GET") return;
  // CSS/JS are handled entirely by the normal browser HTTP cache (see the
  // versioned "?v=" query string on every <link>/<script> tag, plus the
  // backend's Cache-Control headers). Keeping this worker out of that path
  // means there is exactly one cache to invalidate when a file changes,
  // not two that can disagree with each other.
  if (url.pathname.endsWith(".css") || url.pathname.endsWith(".js")) return;

  // Network-first, with the response saved into the runtime cache for next
  // time; falls back to whatever's cached (from install or a previous
  // visit) when the network is unreachable. This is what makes "visit a
  // page once online, reopen it offline later" actually work — the old
  // version only ever matched the two files precached at install.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy)).catch(() => {});
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
