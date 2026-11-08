import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		// Not "localhost": on some systems that binds only ::1, which IPv4 SSH tunnels can't reach.
		host: '127.0.0.1',
		// `beet webui` (or the examples/docker container) serves the API on 8338.
		// Keep the browser's Host header: the API refuses writes whose Origin doesn't match it.
		proxy: { '/api': { target: 'http://127.0.0.1:8338', changeOrigin: false } }
	}
});
