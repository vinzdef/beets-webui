<script lang="ts">
	import { onMount } from 'svelte';
	import {
		api,
		formatLength,
		type Album,
		type AlbumOrder,
		type Item,
		type LibraryUpdatePreview,
		type Page
	} from '$lib/api';

	// 'song' lists tracks instead of albums.
	type Grouping = 'album' | 'artist' | 'path' | 'song';
	const groupings: { value: Grouping; label: string }[] = [
		{ value: 'album', label: 'Albums' },
		{ value: 'artist', label: 'Artists' },
		{ value: 'path', label: 'Folders' },
		{ value: 'song', label: 'Songs' }
	];

	let query = $state('');
	let grouping = $state<Grouping>(storedGrouping());
	let page = $state<Page<Album> | null>(null);
	let songs = $state<Page<Item> | null>(null);
	let loadingMore = $state(false);
	let error = $state<string | null>(null);

	let dialog = $state<HTMLDialogElement>();
	let preview = $state<LibraryUpdatePreview | null>(null);
	let previewError = $state<string | null>(null);
	let updating = $state(false);
	let updated = $state<string | null>(null);

	function storedGrouping(): Grouping {
		try {
			const stored = localStorage.getItem('library.grouping');
			if (groupings.some((g) => g.value === stored)) return stored as Grouping;
		} catch {
			// Storage can be unavailable (private windows, blocked site data).
		}
		return 'album';
	}

	function setGrouping(value: Grouping) {
		grouping = value;
		try {
			localStorage.setItem('library.grouping', value);
		} catch {
			// Not remembered, but still applied.
		}
		search();
	}

	async function search() {
		error = null;
		try {
			if (grouping === 'song') songs = await api.items(query, 0, SONG_PAGE);
			else page = await api.albums(query, grouping satisfies AlbumOrder);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	// Rows are short, so songs load in bigger pages than album covers.
	const SONG_PAGE = 500;

	async function loadMore() {
		loadingMore = true;
		try {
			if (grouping === 'song' && songs) {
				const next = await api.items(query, songs.results.length, SONG_PAGE);
				songs = { ...next, results: [...songs.results, ...next.results] };
			} else if (grouping !== 'song' && page) {
				const next = await api.albums(query, grouping, page.results.length, page.limit);
				page = { ...next, results: [...page.results, ...next.results] };
			}
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loadingMore = false;
		}
	}

	function groupOf(album: Album): string {
		if (grouping === 'artist') return album.albumartist || 'Unknown artist';
		const folder = album.folder ?? '';
		const slash = folder.lastIndexOf('/');
		return slash > 0 ? folder.slice(0, slash) : 'Library folder';
	}

	// The loaded albums in runs that share a heading; the server sorts them so each run is whole.
	const shown = $derived(grouping === 'song' ? songs : page);

	const groups = $derived.by(() => {
		const albums = page?.results ?? [];
		if (grouping === 'album' || grouping === 'song') return [{ name: '', albums }];
		const runs: { name: string; albums: Album[] }[] = [];
		for (const album of albums) {
			const name = groupOf(album);
			if (runs.at(-1)?.name === name) runs.at(-1)!.albums.push(album);
			else runs.push({ name, albums: [album] });
		}
		return runs;
	});

	async function openUpdate() {
		preview = null;
		previewError = null;
		updated = null;
		dialog?.showModal();
		try {
			preview = await api.previewUpdate();
		} catch (e) {
			previewError = e instanceof Error ? e.message : String(e);
		}
	}

	async function update() {
		updating = true;
		try {
			const { removed_items: items, removed_albums: albums } = await api.updateLibrary();
			updated =
				items || albums
					? `Removed ${plural(items, 'track')} and ${plural(albums, 'album')} whose files are gone.`
					: 'Library is up to date.';
			dialog?.close();
			await search();
		} catch (e) {
			previewError = e instanceof Error ? e.message : String(e);
		} finally {
			updating = false;
		}
	}

	function plural(n: number, word: string) {
		return `${n} ${word}${n === 1 ? '' : 's'}`;
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
	<button type="button" onclick={openUpdate}>Update library…</button>
</form>

<div class="toolbar">
	<div class="segmented" role="group" aria-label="Group by">
		{#each groupings as g (g.value)}
			<button
				type="button"
				class:current={grouping === g.value}
				aria-pressed={grouping === g.value}
				onclick={() => setGrouping(g.value)}>{g.label}</button
			>
		{/each}
	</div>
	{#if shown}<span class="meta">{plural(shown.total, grouping === 'song' ? 'song' : 'album')}</span
		>{/if}
</div>

{#if updated}<p class="meta">{updated}</p>{/if}

{#if error}
	<p class="error">{error}</p>
{:else if grouping === 'song'}
	{#if songs}
		<table class="songs">
			<thead>
				<tr>
					<th class="num">#</th>
					<th>Title</th>
					<th>Artist</th>
					<th class="album">Album</th>
					<th class="num year">Year</th>
					<th class="num">Time</th>
				</tr>
			</thead>
			<tbody>
				{#each songs.results as song (song.id)}
					<tr title={song.path ?? undefined}>
						<td class="num">{song.track || ''}</td>
						<td>{song.title}</td>
						<td>{song.artist}</td>
						<td class="album">
							{#if song.album_id}<a href="/albums/{song.album_id}">{song.album}</a
								>{:else}{song.album}{/if}
						</td>
						<td class="num year">{song.year || ''}</td>
						<td class="num">{formatLength(song.length)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
{:else if page}
	{#each groups as group, i (i)}
		<section>
			{#if group.name}<h2>{group.name}</h2>{/if}
			<ul class="grid">
				{#each group.albums as album (album.id)}
					<li>
						<a href="/albums/{album.id}" title={album.folder ?? undefined}>
							<div class="cover">
								<img
									src={api.artUrl(album.id)}
									alt=""
									loading="lazy"
									onerror={(e) => e.currentTarget.remove()}
								/>
							</div>
							<strong>{album.album}</strong>
							<span>{album.albumartist}{album.year ? ` · ${album.year}` : ''}</span>
						</a>
					</li>
				{/each}
			</ul>
		</section>
	{/each}
{/if}
{#if !error && shown && shown.results.length < shown.total}
	<button class="more" disabled={loadingMore} onclick={loadMore}>
		{loadingMore ? 'Loading…' : `Show more (${shown.total - shown.results.length} left)`}
	</button>
{/if}

<dialog bind:this={dialog}>
	<h2>Update library</h2>
	<p>
		Re-reads tags that changed on disk and removes entries whose files are gone. New files aren't
		added: import them instead.
	</p>
	{#if previewError}
		<p class="error">{previewError}</p>
	{:else if !preview}
		<p class="meta">Checking for missing files…</p>
	{:else}
		{#if preview.missing.length}
			<p>
				<strong>{plural(preview.missing.length, 'track')}</strong> will be removed from the library
				because {preview.missing.length === 1 ? 'its file is' : 'their files are'} gone:
			</p>
			<ul class="missing">
				{#each preview.missing as item (item.id)}
					<li>
						{item.artist} – {item.title}
						<span class="path">{item.path}</span>
					</li>
				{/each}
			</ul>
		{:else}
			<p>No files are missing, so nothing will be removed.</p>
		{/if}
		{#if preview.moves_files}
			<p class="meta">Files whose tags changed are moved to match your path format.</p>
		{/if}
	{/if}
	<div class="buttons">
		<button type="button" onclick={() => dialog?.close()}>Cancel</button>
		<button
			type="button"
			class="primary"
			disabled={!preview || updating || !!previewError}
			onclick={update}
		>
			{updating ? 'Updating…' : 'Update'}
		</button>
	</div>
</dialog>

<style>
	form {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}
	input {
		flex: 1;
		min-width: 0;
		padding: 0.5rem;
		font: inherit;
	}
	.toolbar {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 1rem;
		margin-bottom: 1rem;
	}
	.segmented {
		display: flex;
	}
	.segmented button {
		border-radius: 0;
	}
	.segmented button:first-child {
		border-radius: 6px 0 0 6px;
	}
	.segmented button:last-child {
		border-radius: 0 6px 6px 0;
	}
	.segmented button + button {
		margin-left: -1px;
	}
	.segmented button.current {
		background: var(--accent);
		border-color: var(--accent);
		color: white;
	}
	.meta {
		opacity: 0.6;
	}
	.error {
		color: crimson;
	}
	h2 {
		font-size: 1.1em;
		margin: 1.5rem 0 0.75rem;
		word-break: break-word;
	}
	.grid {
		list-style: none;
		padding: 0;
		margin: 0 0 1rem;
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
	.cover {
		width: 100%;
		aspect-ratio: 1;
		border-radius: 4px;
		overflow: hidden;
		background: color-mix(in srgb, currentColor 10%, transparent);
	}
	img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.grid span {
		opacity: 0.7;
		font-size: 0.9em;
	}
	.songs {
		width: 100%;
		border-collapse: collapse;
		table-layout: fixed;
		font-size: 0.9em;
	}
	.songs th {
		text-align: left;
		font-weight: 500;
		opacity: 0.6;
	}
	.songs th,
	.songs td {
		padding: 0.2rem 0.5rem;
		border-bottom: 1px solid var(--line);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.songs tbody tr:hover {
		background: var(--subtle);
	}
	.songs .num {
		width: 3rem;
		text-align: right;
		font-variant-numeric: tabular-nums;
		opacity: 0.7;
	}
	.songs a {
		color: inherit;
	}
	@media (max-width: 640px) {
		.songs .album,
		.songs .year {
			display: none;
		}
	}
	.more {
		display: block;
		margin: 1rem auto;
	}
	dialog {
		width: min(36rem, calc(100vw - 2rem));
		max-height: calc(100vh - 4rem);
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 1.25rem;
		color: inherit;
		background: Canvas;
	}
	dialog::backdrop {
		background: rgb(0 0 0 / 0.4);
	}
	dialog h2 {
		margin-top: 0;
	}
	.missing {
		max-height: 16rem;
		overflow: auto;
		margin: 0;
		padding: 0.5rem 0.75rem;
		list-style: none;
		border: 1px solid var(--line);
		border-radius: 6px;
		font-size: 0.9em;
	}
	.missing li + li {
		margin-top: 0.4rem;
	}
	.path {
		display: block;
		opacity: 0.6;
		font-size: 0.9em;
		word-break: break-all;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		margin-top: 1rem;
	}
</style>
