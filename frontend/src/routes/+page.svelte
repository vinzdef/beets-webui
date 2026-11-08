<script lang="ts">
	import { onMount } from 'svelte';
	import type { Snapshot } from './$types';
	import {
		api,
		formatLength,
		HEALTH_CHECKS,
		type HealthCheck,
		type Album,
		type AlbumOrder,
		type ArtistRow,
		type Item,
		type LibraryUpdatePreview,
		type Page,
		type SongColumn
	} from '$lib/api';
	import BulkEditDialog from '$lib/library/BulkEditDialog.svelte';
	import CoverFillDialog from '$lib/library/CoverFillDialog.svelte';
	import FeatDialog from '$lib/library/FeatDialog.svelte';
	import ShrinkArtDialog from '$lib/library/ShrinkArtDialog.svelte';
	import ToolsMenu from '$lib/library/ToolsMenu.svelte';
	import HealthGauge from '$lib/library/HealthGauge.svelte';

	// 'song' lists tracks instead of albums.
	type Grouping = 'album' | 'artist' | 'song';
	const groupings: { value: Grouping; label: string }[] = [
		{ value: 'album', label: 'Albums' },
		{ value: 'artist', label: 'Artists' },
		{ value: 'song', label: 'Songs' }
	];

	let query = $state('');
	let grouping = $state<Grouping>(storedGrouping());
	// Only albums with this problem ('any' for any); albums views only.
	let problem = $state<HealthCheck | 'any' | ''>('');
	// The artists view also lists tracks on no album, and counts albums and tracks apart.
	type AlbumPage = Page<Album | ArtistRow> & { albums?: number; tracks?: number };
	let page = $state<AlbumPage | null>(null);
	let songs = $state<Page<Item> | null>(null);
	// The songs view's column sort (beets' default order when null) and filter.
	let songSort = $state<{ column: SongColumn; desc: boolean } | null>(null);
	let songFilter = $state<'' | 'singletons' | 'on_album'>('');
	let loadingMore = $state(false);
	let error = $state<string | null>(null);

	let dialog = $state<HTMLDialogElement>();
	let preview = $state<LibraryUpdatePreview | null>(null);
	let previewError = $state<string | null>(null);
	let updating = $state(false);
	let updated = $state<string | null>(null);

	// Picking albums or songs for a bulk edit; ids of whichever the view lists.
	let selecting = $state(false);
	let selected = $state<number[]>([]);
	let bulkEditing = $state(false);
	let fillingCovers = $state(false);
	let shrinkingArt = $state(false);
	let movingFeat = $state(false);
	// Bumped when covers were added, so the grid doesn't show the browser's cached "no cover".
	let artVersion = $state(0);
	// Bumped after changes, so the health gauge checks again.
	let healthVersion = $state(0);

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

	// Bumped by each search and by restoring a snapshot, so a slower earlier search can't
	// overwrite newer results.
	let generation = 0;

	function toggle(id: number) {
		selected = selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id];
	}

	function stopSelecting() {
		selecting = false;
		selected = [];
	}

	async function bulkEdited(saved: boolean) {
		bulkEditing = false;
		if (!saved) return;
		updated = `Saved ${plural(selected.length, grouping === 'song' ? 'song' : 'album')}.`;
		stopSelecting();
		healthVersion++;
		await search();
	}

	async function search() {
		// A new search supersedes a Show more in flight (see loadMore).
		loadingMore = false;
		const current = ++generation;
		selected = [];
		error = null;
		try {
			if (grouping === 'song') {
				const result = await api.items(query, 0, SONG_PAGE, songOrder());
				if (current === generation) songs = result;
			} else {
				const result = withTracks()
					? await api.artists(query, 0, 100)
					: await api.albums(query, grouping satisfies AlbumOrder, 0, 100, problem);
				if (current === generation) page = result;
			}
		} catch (e) {
			if (current === generation) error = e instanceof Error ? e.message : String(e);
		}
	}

	// Coming back to the library (e.g. from an album) brings back the search, the view, the
	// loaded results and, since they're there straight away, the scroll position.
	export const snapshot: Snapshot<{
		query: string;
		grouping: Grouping;
		problem: HealthCheck | 'any' | '';
		page: AlbumPage | null;
		songs: Page<Item> | null;
		songSort?: typeof songSort;
		songFilter?: typeof songFilter;
	}> = {
		capture: () => $state.snapshot({ query, grouping, problem, page, songs, songSort, songFilter }),
		restore: (saved) => {
			generation++;
			loadingMore = false;
			loadingMore = false;
			({ query, grouping, page, songs } = saved);
			problem = saved.problem ?? '';
			songSort = saved.songSort ?? null;
			songFilter = saved.songFilter ?? '';
		}
	};

	function songOrder() {
		return { sort: songSort?.column, desc: songSort?.desc, only: songFilter };
	}

	/** Sort by a column; clicking it again reverses the order. */
	function sortSongs(column: SongColumn) {
		songSort = { column, desc: songSort?.column === column && !songSort.desc };
		search();
	}

	const songColumns: { column: SongColumn; label: string; class?: string }[] = [
		{ column: 'track', label: '#', class: 'num' },
		{ column: 'title', label: 'Title' },
		{ column: 'artist', label: 'Artist' },
		{ column: 'album', label: 'Album', class: 'album' }
	];

	/** Show only the albums with a problem, e.g. from the health details. */
	function showProblem(check: HealthCheck | 'any') {
		problem = check;
		if (grouping === 'song') grouping = 'album';
		search();
	}

	// Rows are short, so songs load in bigger pages than album covers.
	const SONG_PAGE = 500;

	async function loadMore() {
		// A search that starts meanwhile makes these results stale: they're then dropped.
		const current = generation;
		loadingMore = true;
		try {
			if (grouping === 'song' && songs) {
				const next = await api.items(query, songs.results.length, SONG_PAGE, songOrder());
				if (current === generation)
					songs = { ...next, results: [...songs.results, ...next.results] };
			} else if (grouping !== 'song' && page) {
				const next: AlbumPage = withTracks()
					? await api.artists(query, page.results.length, page.limit)
					: await api.albums(query, grouping, page.results.length, page.limit, problem);
				if (current === generation) page = { ...next, results: [...page.results, ...next.results] };
			}
		} catch (e) {
			if (current === generation) error = e instanceof Error ? e.message : String(e);
		} finally {
			// A stale request mustn't re-enable Show more while a newer one is loading.
			if (current === generation) loadingMore = false;
		}
	}

	const shown = $derived(grouping === 'song' ? songs : page);

	/** The artists view lists tracks on no album too; health checks are about albums only. */
	function withTracks() {
		return grouping === 'artist' && !problem;
	}

	function isTrack(row: Album | ArtistRow): row is Item & { kind: 'track' } {
		return row.kind === 'track';
	}

	const shownAlbums = $derived((page?.results ?? []).filter((r) => !isTrack(r)));

	// The loaded rows in runs that share an artist heading; the server sorts them by artist, each
	// artist's albums before their loose tracks.
	const groups = $derived.by(() => {
		const rows = page?.results ?? [];
		if (grouping !== 'artist') return [{ name: '', albums: rows as Album[], tracks: [] }];
		const runs: { name: string; albums: Album[]; tracks: Item[] }[] = [];
		for (const row of rows) {
			const name = (isTrack(row) ? row.artist : row.albumartist) || 'Unknown artist';
			let run = runs.at(-1);
			// The server's sort ignores case, so runs do too.
			if (run?.name.toLowerCase() !== name.toLowerCase()) {
				run = { name, albums: [], tracks: [] };
				runs.push(run);
			}
			if (isTrack(row)) run.tracks.push(row);
			else run.albums.push(row);
		}
		return runs;
	});

	/** What the view lists: "12 albums", or "12 albums · 3 loose tracks" with tracks on no album. */
	const count = $derived.by(() => {
		if (!shown) return '';
		if (grouping === 'song') return plural(shown.total, 'song');
		if (page?.tracks == null) return plural(shown.total, 'album');
		const albums = plural(page.albums ?? 0, 'album');
		return page.tracks ? `${albums} · ${plural(page.tracks, 'loose track')}` : albums;
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
			healthVersion++;
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
	<ToolsMenu
		items={[
			{ label: 'Update library…', action: openUpdate },
			{ label: 'Fill missing covers…', action: () => (fillingCovers = true) },
			{ label: 'Shrink embedded covers…', action: () => (shrinkingArt = true) },
			{ label: 'Move "feat." into titles…', action: () => (movingFeat = true) }
		]}
	/>
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
	{#if grouping === 'song'}
		<select
			bind:value={songFilter}
			onchange={search}
			aria-label="Show songs"
			class:active={songFilter}
		>
			<option value="">All songs</option>
			<option value="singletons">Not on an album</option>
			<option value="on_album">On an album</option>
		</select>
	{:else}
		<select bind:value={problem} onchange={search} aria-label="Show albums" class:active={problem}>
			<option value="">All albums</option>
			<option value="any">With problems</option>
			{#each HEALTH_CHECKS as check (check.id)}
				<option value={check.id}>{check.label}</option>
			{/each}
		</select>
	{/if}
	{#if shown}<span class="meta">{count}</span>{/if}
	<div class="selection">
		{#if selecting}
			<span class="meta">{selected.length} selected</span>
			<button
				type="button"
				onclick={() =>
					(selected = (grouping === 'song' ? (songs?.results ?? []) : shownAlbums).map(
						(r) => r.id
					))}>Select all shown</button
			>
			<button type="button" disabled={!selected.length} onclick={() => (bulkEditing = true)}
				>Edit…</button
			>
			<button type="button" onclick={stopSelecting}>Done</button>
		{:else}
			<button type="button" onclick={() => (selecting = true)}>Select</button>
		{/if}
		{#key healthVersion}
			<HealthGauge
				onupdate={openUpdate}
				onfillcovers={() => (fillingCovers = true)}
				onshow={showProblem}
			/>
		{/key}
	</div>
</div>

{#if movingFeat}
	<FeatDialog
		onclose={(changed) => {
			movingFeat = false;
			if (changed) search();
		}}
	/>
{/if}

{#if shrinkingArt}
	<ShrinkArtDialog onclose={() => (shrinkingArt = false)} />
{/if}

{#if fillingCovers}
	<CoverFillDialog
		onclose={(filled) => {
			fillingCovers = false;
			if (filled) {
				artVersion = Date.now();
				healthVersion++;
			}
		}}
	/>
{/if}

{#if bulkEditing}
	<BulkEditDialog
		kind={grouping === 'song' ? 'songs' : 'albums'}
		ids={selected}
		onclose={bulkEdited}
	/>
{/if}

{#if updated}<p class="meta">{updated}</p>{/if}

{#if error}
	<p class="error">{error}</p>
{:else if grouping === 'song'}
	{#if songs}
		<table class="songs">
			<thead>
				<tr>
					{#if selecting}<th class="check"></th>{/if}
					{#each songColumns as c (c.column)}
						<th
							class={c.class}
							aria-sort={songSort?.column === c.column
								? songSort.desc
									? 'descending'
									: 'ascending'
								: undefined}
						>
							<button type="button" class="sort" onclick={() => sortSongs(c.column)}
								>{c.label}{songSort?.column === c.column
									? songSort.desc
										? ' ▼'
										: ' ▲'
									: ''}</button
							>
						</th>
					{/each}
					<th class="num year">Year</th>
					<th class="num">Time</th>
				</tr>
			</thead>
			<tbody>
				{#each songs.results as song (song.id)}
					<tr title={song.path ?? undefined} class:selected={selected.includes(song.id)}>
						{#if selecting}
							<td class="check">
								<input
									type="checkbox"
									checked={selected.includes(song.id)}
									onchange={() => toggle(song.id)}
									aria-label="Select {song.title}"
								/>
							</td>
						{/if}
						<td class="num">{song.track || ''}</td>
						<td><a href="/songs/{song.id}">{song.title}</a></td>
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
			{#if group.albums.length}
				<ul class="grid">
					{#each group.albums as album (album.id)}
						<li>
							<a
								href="/albums/{album.id}"
								class:selected={selected.includes(album.id)}
								onclick={(e) => {
									if (!selecting) return;
									e.preventDefault();
									toggle(album.id);
								}}
							>
								<div class="cover">
									{#if selecting}
										<input
											class="pick"
											type="checkbox"
											tabindex="-1"
											checked={selected.includes(album.id)}
											aria-hidden="true"
										/>
									{/if}
									<img
										src={api.artUrl(album.id, artVersion)}
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
			{/if}
			{#if group.tracks.length}
				<table class="songs loose">
					<caption>Not on an album</caption>
					<tbody>
						{#each group.tracks as song (song.id)}
							<tr title={song.path ?? undefined}>
								<td><a href="/songs/{song.id}">{song.title || 'Untitled'}</a></td>
								<td class="album">{song.album}</td>
								<td class="num year">{song.year || ''}</td>
								<td class="num">{formatLength(song.length)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
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
		position: relative;
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
		text-decoration: none;
	}
	.songs a:hover {
		text-decoration: underline;
	}
	.songs .check {
		width: 2rem;
	}
	button.sort {
		all: unset;
		cursor: pointer;
		white-space: nowrap;
	}
	button.sort:hover,
	button.sort:focus-visible {
		text-decoration: underline;
	}
	/* An artist's tracks on no album, under their albums. */
	.songs.loose {
		margin-top: 0.75rem;
	}
	.songs caption {
		text-align: left;
		font-size: 0.85em;
		opacity: 0.6;
		padding: 0 0.5rem 0.25rem;
	}
	.songs tr.selected {
		background: color-mix(in srgb, var(--accent) 12%, transparent);
	}
	select {
		font: inherit;
		padding: 0.35rem 0.4rem;
	}
	select.active {
		border-color: var(--warn);
		color: var(--warn);
	}
	.selection {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-left: auto;
	}
	.pick {
		position: absolute;
		top: 0.4rem;
		left: 0.4rem;
		width: 1.2rem;
		height: 1.2rem;
		margin: 0;
		pointer-events: none;
	}
	.grid a.selected .cover {
		outline: 3px solid var(--accent);
		outline-offset: 2px;
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
