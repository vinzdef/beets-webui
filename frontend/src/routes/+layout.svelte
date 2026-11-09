<script lang="ts">
	import { page } from '$app/state';
	import PlayerBar from '$lib/PlayerBar.svelte';
	import { player } from '$lib/player.svelte';

	let { children } = $props();
</script>

<header>
	<a class="brand" href="/">beets</a>
	<nav>
		<a
			href="/"
			class:current={page.url.pathname === '/' ||
				page.url.pathname.startsWith('/albums') ||
				page.url.pathname.startsWith('/songs')}>Library</a
		>
		<a href="/import" class:current={page.url.pathname.startsWith('/import')}>Import</a>
		<a href="/log" class:current={page.url.pathname.startsWith('/log')}>Log</a>
	</nav>
</header>

<main class:with-player={player.current}>
	{@render children()}
</main>

<PlayerBar />

<style>
	:global(:root) {
		color-scheme: light dark;
		font-family: system-ui, sans-serif;
		--accent: #3a6ff0;
		--ok: #1e8a4c;
		--warn: #b26a00;
		--bad: #c62f3a;
		--line: color-mix(in srgb, currentColor 12%, transparent);
		--subtle: color-mix(in srgb, currentColor 8%, transparent);
	}
	@media (prefers-color-scheme: dark) {
		:global(:root) {
			--accent: #7ea2ff;
			--ok: #5fd08f;
			--warn: #f0b153;
			--bad: #ff7a83;
		}
	}
	:global(body) {
		margin: 0;
	}
	:global(button) {
		font: inherit;
		color: inherit;
		background: var(--subtle);
		border: 1px solid var(--line);
		border-radius: 6px;
		padding: 0.4rem 0.8rem;
		cursor: pointer;
	}
	:global(button:hover:not(:disabled)) {
		border-color: color-mix(in srgb, currentColor 35%, transparent);
	}
	:global(button:disabled) {
		opacity: 0.5;
		cursor: default;
	}
	:global(button.primary) {
		background: var(--accent);
		border-color: var(--accent);
		color: white;
	}
	:global(button.danger) {
		color: var(--bad);
	}
	:global(input:not([type='checkbox'])) {
		font: inherit;
		padding: 0.4rem 0.5rem;
		border: 1px solid var(--line);
		border-radius: 6px;
		background: transparent;
		color: inherit;
	}
	header {
		display: flex;
		align-items: center;
		gap: 1.5rem;
		padding: 0.75rem 1.5rem;
		border-bottom: 1px solid var(--line);
	}
	header a {
		color: inherit;
		text-decoration: none;
	}
	.brand {
		font-weight: 600;
	}
	nav {
		display: flex;
		gap: 1rem;
	}
	nav a {
		opacity: 0.65;
	}
	nav a.current {
		opacity: 1;
		font-weight: 500;
	}
	main {
		padding: 1.5rem;
		max-width: 1200px;
		margin: 0 auto;
	}
	/* Room for the player bar, so it never covers the end of the page. */
	main.with-player {
		padding-bottom: 9rem;
	}
</style>
