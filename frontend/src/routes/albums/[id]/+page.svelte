<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, imports, type AlbumDetail, type AlbumEdit, type Item } from '$lib/api';

	const albumFields = [
		{ key: 'album', label: 'Album' },
		{ key: 'albumartist', label: 'Album artist' },
		{ key: 'year', label: 'Year' },
		{ key: 'genres', label: 'Genres', hint: 'Separate with ;' },
		{ key: 'label', label: 'Label' },
		{ key: 'catalognum', label: 'Catalog number' },
		{ key: 'country', label: 'Country' }
	];
	const itemFields = ['disc', 'track', 'title', 'artist'] as const;

	let album = $state<AlbumDetail | null>(null);
	let error = $state<string | null>(null);
	let editing = $state(false);
	let busy = $state(false);
	// The form's values, as strings keyed by field (and by track id for tracks).
	let albumForm = $state<Record<string, string>>({});
	let itemForms = $state<Record<number, Record<string, string>>>({});

	$effect(() => {
		const id = Number(page.params.id);
		album = null;
		error = null;
		editing = false;
		api.album(id).then(
			(a) => (album = a),
			(e) => (error = e instanceof Error ? e.message : String(e))
		);
	});

	/** A field as the text beets would parse back: lists joined by "; ", zero years blank. */
	function text(value: unknown): string {
		if (Array.isArray(value)) return value.join('; ');
		if (value == null || value === 0) return '';
		return String(value);
	}

	function startEditing() {
		if (!album) return;
		albumForm = Object.fromEntries(albumFields.map((f) => [f.key, text(album![f.key])]));
		itemForms = Object.fromEntries(
			album.items.map((item) => [
				item.id,
				Object.fromEntries(itemFields.map((f) => [f, text(item[f])]))
			])
		);
		error = null;
		editing = true;
	}

	/** Only the fields that changed, so untouched tracks aren't rewritten. */
	function changes(): AlbumEdit {
		const edit: AlbumEdit = { album: {}, items: {} };
		for (const f of albumFields) {
			if (albumForm[f.key] !== text(album![f.key])) edit.album![f.key] = albumForm[f.key];
		}
		for (const item of album!.items) {
			const changed: Record<string, string> = {};
			for (const f of itemFields) {
				if (itemForms[item.id][f] !== text(item[f])) changed[f] = itemForms[item.id][f];
			}
			if (Object.keys(changed).length) edit.items![item.id] = changed;
		}
		return edit;
	}

	async function save() {
		const edit = changes();
		if (!Object.keys(edit.album!).length && !Object.keys(edit.items!).length) {
			editing = false;
			return;
		}
		busy = true;
		error = null;
		try {
			album = await api.editAlbum(album!.id, edit);
			editing = false;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	async function reimport() {
		busy = true;
		error = null;
		try {
			// Ask about every match: the point is to choose one again.
			await imports.reimport(album!.id, { mode: 'timid' });
			await goto('/import');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	function duration(seconds: number) {
		const s = Math.round(seconds);
		return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	}

	function trackNumber(item: Item) {
		const disc = Number(item.disc);
		return Number(album?.disctotal) > 1 && disc ? `${disc}-${item.track}` : String(item.track);
	}
</script>

{#if album}
	<header>
		<div class="cover">
			<img src={api.artUrl(album.id)} alt="" onerror={(e) => e.currentTarget.remove()} />
		</div>
		<div class="heading">
			<h1>{album.album}</h1>
			<p>{album.albumartist}{album.year ? ` · ${album.year}` : ''}</p>
			{#if text(album.genres) || album.label}
				<p class="meta">{[text(album.genres), album.label].filter(Boolean).join(' · ')}</p>
			{/if}
			{#if !editing}
				<div class="buttons">
					<button onclick={startEditing}>Edit</button>
					<button
						disabled={busy}
						onclick={reimport}
						title="Look up matches for this album again and choose one. Nothing is copied; files are renamed only if the new tags change their path"
						>Re-import…</button
					>
				</div>
			{/if}
		</div>
	</header>

	{#if error}<p class="error">{error}</p>{/if}

	{#if editing}
		<form
			onsubmit={(e) => {
				e.preventDefault();
				save();
			}}
		>
			<div class="fields">
				{#each albumFields as f (f.key)}
					<label>
						<span>{f.label}</span>
						<input bind:value={albumForm[f.key]} placeholder={f.hint} />
					</label>
				{/each}
			</div>
			<table>
				<thead>
					<tr>
						<th class="num">Disc</th>
						<th class="num">#</th>
						<th>Title</th>
						<th>Artist</th>
					</tr>
				</thead>
				<tbody>
					{#each album.items as item (item.id)}
						<tr>
							<td class="num"><input bind:value={itemForms[item.id].disc} inputmode="numeric" /></td
							>
							<td class="num"
								><input bind:value={itemForms[item.id].track} inputmode="numeric" /></td
							>
							<td><input bind:value={itemForms[item.id].title} /></td>
							<td><input bind:value={itemForms[item.id].artist} /></td>
						</tr>
					{/each}
				</tbody>
			</table>
			<p class="meta">
				Saving writes the tags to the files and, if your import settings move or copy files, renames
				them to match.
			</p>
			<div class="buttons">
				<button type="button" disabled={busy} onclick={() => (editing = false)}>Cancel</button>
				<button class="primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
			</div>
		</form>
	{:else}
		<table>
			<tbody>
				{#each album.items as item (item.id)}
					<tr>
						<td class="num">{trackNumber(item)}</td>
						<td>{item.title}</td>
						<td>{item.artist}</td>
						<td class="num">{duration(item.length)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
{:else if error}
	<p class="error">{error}</p>
{:else}
	<p>Loading…</p>
{/if}

<style>
	header {
		display: flex;
		gap: 1.25rem;
		align-items: flex-end;
		flex-wrap: wrap;
		margin-bottom: 1.5rem;
	}
	.cover {
		width: 160px;
		aspect-ratio: 1;
		border-radius: 4px;
		overflow: hidden;
		flex: none;
		background: color-mix(in srgb, currentColor 10%, transparent);
	}
	.cover img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.heading {
		min-width: 0;
		flex: 1;
	}
	h1 {
		margin: 0 0 0.25rem;
	}
	.heading p {
		margin: 0 0 0.25rem;
	}
	.meta {
		opacity: 0.6;
		font-size: 0.9em;
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-top: 0.75rem;
	}
	form .buttons {
		justify-content: flex-end;
	}
	.fields {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
		gap: 0.75rem;
		margin-bottom: 1.25rem;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
	}
	label span {
		font-size: 0.85em;
		opacity: 0.7;
	}
	input {
		font: inherit;
		padding: 0.35rem 0.5rem;
		min-width: 0;
		width: 100%;
		box-sizing: border-box;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th {
		text-align: left;
		font-weight: 500;
		opacity: 0.6;
		padding: 0.3rem 0.5rem;
	}
	td {
		padding: 0.4rem 0.5rem;
		border-bottom: 1px solid color-mix(in srgb, currentColor 10%, transparent);
	}
	.num {
		width: 4rem;
		font-variant-numeric: tabular-nums;
	}
	td.num {
		opacity: 0.6;
	}
	form td.num {
		opacity: 1;
	}
	.error {
		color: crimson;
	}
</style>
