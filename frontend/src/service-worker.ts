/// <reference types="@sveltejs/kit" />
/// <reference no-default-lib="true"/>
/// <reference lib="esnext" />
/// <reference lib="webworker" />

// Keeps the app shell available so the installed app opens without a round trip; the library
// itself always comes from the server, so /api is never cached.
import { build, files, version } from '$service-worker';

const sw = self as unknown as ServiceWorkerGlobalScope;
const CACHE = `shell-${version}`;
const ASSETS = new Set([...build, ...files]);
// Every page is the same SPA fallback, cached under one key.
const SHELL = '/';

sw.addEventListener('install', (event) => {
	event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll([...ASSETS, SHELL])));
});

sw.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
	);
});

sw.addEventListener('fetch', (event) => {
	const { request } = event;
	const url = new URL(request.url);
	if (request.method !== 'GET' || url.origin !== sw.location.origin) return;
	if (url.pathname.startsWith('/api/')) return;

	if (ASSETS.has(url.pathname)) {
		// Cached per app version, so a cached copy always belongs to the page that asks for it.
		event.respondWith(caches.match(url.pathname).then((hit) => hit ?? fetch(request)));
	} else if (request.mode === 'navigate') {
		// The network first, so a new version shows up straight away; the shell when offline.
		event.respondWith(
			fetch(request).catch(async () => (await caches.match(SHELL)) ?? Response.error())
		);
	}
});
