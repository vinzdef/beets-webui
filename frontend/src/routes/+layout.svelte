<script lang="ts">
	let { children } = $props();
</script>

<header>
	<a href="/">beets</a>
</header>

<main>
	{@render children()}
</main>

<style>
	:global(:root) {
		color-scheme: light dark;
		font-family: system-ui, sans-serif;
	}
	:global(body) {
		margin: 0;
	}
	header {
		padding: 0.75rem 1.5rem;
		border-bottom: 1px solid color-mix(in srgb, currentColor 15%, transparent);
		font-weight: 600;
	}
	header a {
		color: inherit;
		text-decoration: none;
	}
	main {
		padding: 1.5rem;
		max-width: 1200px;
		margin: 0 auto;
	}
</style>
