<script lang="ts">
	import { page } from '$app/state';
	import { api, formatKbps, formatLength, type Album, type ArtistDetail } from '$lib/api';

	let artist = $state<ArtistDetail | null>(null);
	let error = $state<string | null>(null);

	// The name is in the query string (?name=…), as names can hold slashes.
	$effect(() => {
		const name = page.url.searchParams.get('name') ?? '';
		artist = null;
		error = null;
		if (!name) {
			error = 'No artist given.';
			return;
		}
		api.artist(name).then(
			(a) => (artist = a),
			(e) => (error = e instanceof Error ? e.message : String(e))
		);
	});

	function plural(n: number, word: string) {
		return `${n} ${word}${n === 1 ? '' : 's'}`;
	}

	const summary = $derived(
		artist
			? [
					artist.albums.length && plural(artist.albums.length, 'album'),
					artist.appears_on.length && `on ${plural(artist.appears_on.length, 'other album')}`,
					artist.tracks.length && plural(artist.tracks.length, 'track') + ' not on an album'
				]
					.filter(Boolean)
					.join(' · ')
			: ''
	);
</script>

{#snippet grid(albums: Album[], showArtist: boolean)}
	<ul class="grid">
		{#each albums as album (album.id)}
			<li>
				<a href="/albums/{album.id}">
					<div class="cover">
						<img
							src={api.artUrl(album.id, 0, true)}
							alt=""
							loading="lazy"
							decoding="async"
							onerror={(e) => e.currentTarget.remove()}
						/>
					</div>
					<strong>{album.album}</strong>
					<span>{[showArtist && album.albumartist, album.year].filter(Boolean).join(' · ')}</span>
				</a>
			</li>
		{/each}
	</ul>
{/snippet}

{#if artist}
	<h1>{artist.name}</h1>
	<p class="meta">{summary}</p>

	{#if artist.albums.length}
		<h2>Albums</h2>
		{@render grid(artist.albums, false)}
	{/if}

	{#if artist.appears_on.length}
		<h2>Appears on</h2>
		{@render grid(artist.appears_on, true)}
	{/if}

	{#if artist.tracks.length}
		<h2>Not on an album</h2>
		<div class="scroll">
			<table class="songs">
				<thead>
					<tr>
						<th>Title</th>
						<th class="album">Album</th>
						<th class="num kbps">kbps</th>
						<th class="num year">Year</th>
						<th class="num">Time</th>
					</tr>
				</thead>
				<tbody>
					{#each artist.tracks as song (song.id)}
						<tr title={song.path ?? undefined}>
							<td><a href="/songs/{song.id}">{song.title || 'Untitled'}</a></td>
							<td class="album">{song.album}</td>
							<td class="num kbps">{formatKbps(song.bitrate)}</td>
							<td class="num year">{song.year || ''}</td>
							<td class="num">{formatLength(song.length)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
{:else if error}
	<p class="error">{error}</p>
{:else}
	<p>Loading…</p>
{/if}

<style>
	h1 {
		margin: 0 0 0.25rem;
		word-break: break-word;
	}
	h2 {
		font-size: 1.1em;
		margin: 1.5rem 0 0.75rem;
	}
	.meta {
		margin: 0;
		opacity: 0.6;
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
	.songs .kbps {
		width: 4.5rem;
	}
	.songs a {
		color: inherit;
		text-decoration: none;
	}
	.songs a:hover {
		text-decoration: underline;
	}
	/* On narrow screens tables keep every column and scroll sideways instead. */
	.scroll {
		overflow-x: auto;
	}
	.scroll > table {
		min-width: 40rem;
	}
</style>
