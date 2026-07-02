const VERSION = "runforfan-pwa-v1"
const SHELL_CACHE = `${VERSION}-shell`
const RUNTIME_CACHE = `${VERSION}-runtime`
const APP_SCOPE_URL = new URL(self.registration.scope)
const APP_SCOPE_PATH = APP_SCOPE_URL.pathname.endsWith("/") ? APP_SCOPE_URL.pathname : `${APP_SCOPE_URL.pathname}/`

const fromScope = (path) => new URL(path, APP_SCOPE_URL).toString()

const CORE_ASSETS = [
  fromScope("./offline.html"),
  fromScope("./icons/runforfan-icon.svg"),
  fromScope("./icons/runforfan-icon-192.png"),
  fromScope("./icons/runforfan-icon-512.png"),
  fromScope("./icons/runforfan-icon-maskable-512.png"),
]

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(CORE_ASSETS))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith("runforfan-pwa-") && key !== SHELL_CACHE && key !== RUNTIME_CACHE)
          .map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  )
})

const isSameOrigin = (url) => url.origin === self.location.origin
const isApiRequest = (url) => isSameOrigin(url) && (url.pathname === "/api" || url.pathname.startsWith("/api/"))
const isAppRequest = (url) => isSameOrigin(url) && url.pathname.startsWith(APP_SCOPE_PATH)
const isStaticAsset = (url) => isAppRequest(url) && (
  url.pathname.startsWith(`${APP_SCOPE_PATH}assets/`) ||
  url.pathname.startsWith(`${APP_SCOPE_PATH}icons/`) ||
  url.pathname === `${APP_SCOPE_PATH}offline.html`
)

const networkFirstNavigation = async (request) => {
  const cache = await caches.open(SHELL_CACHE)

  try {
    return await fetch(request)
  } catch {
    return await cache.match(fromScope("./offline.html")) || new Response("Runforfan requires an internet connection.", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    })
  }
}

const cacheFirstStaticAsset = async (request) => {
  const cached = await caches.match(request)

  if (cached) {
    return cached
  }

  const response = await fetch(request)

  if (response.ok) {
    const cache = await caches.open(RUNTIME_CACHE)
    cache.put(request, response.clone())
  }

  return response
}

self.addEventListener("fetch", (event) => {
  const { request } = event

  if (request.method !== "GET") {
    return
  }

  const url = new URL(request.url)

  if (isApiRequest(url)) {
    return
  }

  if (request.mode === "navigate" && isAppRequest(url)) {
    event.respondWith(networkFirstNavigation(request))
    return
  }

  if (isStaticAsset(url)) {
    event.respondWith(cacheFirstStaticAsset(request))
  }
})
