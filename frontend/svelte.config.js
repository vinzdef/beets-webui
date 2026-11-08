import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Build straight into the Python package so the plugin can serve it.
		adapter: adapter({
			pages: '../src/beetsplug/webui/static',
			assets: '../src/beetsplug/webui/static',
			fallback: 'index.html'
		})
	}
};

export default config;
