<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type Album, type Page } from '$lib/api';

	let query = $state('');
	let page = $state<Page<Album> | null>(null);
	let error = $state<string | null>(null);

	async function search() {
		error = null;
		try {
			page = await api.albums(query);
		} catch (e) {
			error = String(e);
		}
	}

	onMount(search);
</script>

<form
	onsubmit={(e) => {
		e.preventDefault();
		search();
	}}
>
	<input bind:value={query} placeholder="beets query, e.g. artist:radiohead year:1990..1999" />
	<button>Search</button>
</form>

{#if error}
	<p class="error">{error}</p>
{:else if page}
	<p class="meta">{page.total} albums</p>
	<ul class="grid">
		{#each page.results as album (album.id)}
			<li>
				<a href="/albums/{album.id}">
					{#if album.artpath}
						<img src={api.artUrl(album.id)} alt="" loading="lazy" />
					{:else}
						<div class="noart"></div>
					{/if}
					<strong>{album.album}</strong>
					<span>{album.albumartist}{album.year ? ` · ${album.year}` : ''}</span>
				</a>
			</li>
		{/each}
	</ul>
{/if}

<style>
	form {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}
	input {
		flex: 1;
		padding: 0.5rem;
		font: inherit;
	}
	.meta {
		opacity: 0.6;
	}
	.error {
		color: crimson;
	}
	.grid {
		list-style: none;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: 1.25rem;
	}
	.grid a {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		color: inherit;
		text-decoration: none;
	}
	img,
	.noart {
		width: 100%;
		aspect-ratio: 1;
		object-fit: cover;
		border-radius: 4px;
		background: color-mix(in srgb, currentColor 10%, transparent);
	}
	span {
		opacity: 0.7;
		font-size: 0.9em;
	}
</style>
