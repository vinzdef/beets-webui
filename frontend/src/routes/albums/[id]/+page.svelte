<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		fieldText as text,
		formatLength,
		imports,
		type AlbumDetail,
		type AlbumEdit,
		type ArtSource,
		type Item
	} from '$lib/api';

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
	let notice = $state<string | null>(null);
	// Bumped when the art changes, so the browser doesn't show the cached image.
	let artVersion = $state(0);
	let fileInput = $state<HTMLInputElement>();

	const artSources: Record<ArtSource, string> = {
		file: "Cover from beets' art file.",
		folder: "Cover from an image in the album's folder, which beets doesn't track yet.",
		embedded: 'Cover embedded in the files; beets has no art file for it yet.'
	};

	$effect(() => {
		const id = Number(page.params.id);
		album = null;
		error = null;
		notice = null;
		editing = false;
		api.album(id).then(
			(a) => (album = a),
			(e) => (error = e instanceof Error ? e.message : String(e))
		);
	});

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

	async function refresh() {
		const ok = confirm(
			"Fetch this release from MusicBrainz again and apply its current data? Tags MusicBrainz provides replace yours, including edits you've made to them."
		);
		if (!ok) return;
		busy = true;
		error = null;
		notice = null;
		try {
			album = await api.refreshAlbum(album!.id);
			notice = 'Refreshed from MusicBrainz.';
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	let deleteDialog = $state<HTMLDialogElement>();
	let deleteFiles = $state(true);

	// Where the album's files live, to show what deleting removes.
	const folder = $derived(
		album?.items[0]?.path ? album.items[0].path.slice(0, album.items[0].path.lastIndexOf('/')) : ''
	);

	async function deleteAlbum() {
		busy = true;
		error = null;
		try {
			await api.deleteAlbum(album!.id, deleteFiles);
			deleteDialog?.close();
			await goto('/');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			deleteDialog?.close();
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

	/** Run an art action, then reload the album to pick up where its art now comes from. */
	async function artAction(action: () => Promise<unknown>, done: string) {
		busy = true;
		error = null;
		notice = null;
		try {
			await action();
			album = await api.album(album!.id);
			artVersion = Date.now();
			notice = done;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	function upload(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = '';
		if (file) artAction(() => api.uploadArt(album!.id, file), 'Uploaded the cover.');
	}

	// The tracks by disc, as the match screen shows them; the server sends them in album order.
	const discs = $derived.by(() => {
		const groups: { disc: number; items: Item[] }[] = [];
		for (const item of album?.items ?? []) {
			const disc = Number(item.disc) || 1;
			if (groups.at(-1)?.disc === disc) groups.at(-1)!.items.push(item);
			else groups.push({ disc, items: [item] });
		}
		return groups;
	});
	const multiDisc = $derived(discs.length > 1);
</script>

{#if album}
	<header>
		<div class="cover">
			{#key artVersion}
				<img
					src={api.artUrl(album.id, artVersion)}
					alt=""
					onerror={(e) => e.currentTarget.remove()}
				/>
			{/key}
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
					{#if album.can_refresh}
						<button
							disabled={busy}
							onclick={refresh}
							title="Fetch the release this album is matched to again, for corrections made on MusicBrainz since you imported it"
							>Refresh from MusicBrainz</button
						>
					{/if}
					<button
						class="danger"
						disabled={busy}
						onclick={() => {
							deleteFiles = true;
							deleteDialog?.showModal();
						}}>Delete…</button
					>
				</div>
			{/if}
			<!-- Cover changes save straight away, so they work while editing the fields too. -->
			<div class="buttons art">
				<button
					disabled={busy}
					title="Look for a cover with the fetchart plugin's sources, replacing the current one"
					onclick={() => artAction(() => api.fetchArt(album!.id), 'Fetched a new cover.')}
					>Fetch cover</button
				>
				<button disabled={busy} onclick={() => fileInput?.click()}>Upload cover…</button>
				<input
					bind:this={fileInput}
					type="file"
					accept="image/jpeg,image/png,image/webp"
					hidden
					onchange={upload}
				/>
				{#if album.art_source === 'folder' || album.art_source === 'embedded'}
					<button
						disabled={busy}
						title="Save it as the album's cover file (cover.jpg by default), so beets and other players use it"
						onclick={() =>
							artAction(() => api.saveArt(album!.id), 'Saved the cover as an art file.')}
						>Save as art file</button
					>
				{/if}
				{#if album.art_source === 'file'}
					<button
						disabled={busy}
						title="Write the cover into every track's tags, for players that only read embedded art"
						onclick={() =>
							artAction(() => api.embedArt(album!.id), 'Embedded the cover in every track.')}
						>Embed in files</button
					>
				{/if}
			</div>
			<p class="meta">{album.art_source ? artSources[album.art_source] : 'No cover yet.'}</p>
		</div>
	</header>

	{#if album.problems.length && !editing}
		<section class="problems" aria-label="Problems">
			<ul>
				{#each album.problems as problem (problem.id)}
					<li>
						<strong>{problem.label}.</strong>
						{problem.detail}
						{#if problem.id === 'missing_files'}
							Run <a href="/">Update library…</a> on the Library page to drop them.
						{:else if problem.id === 'missing_tracks'}
							Re-import to see the release's tracklist and what you're missing.
							<button disabled={busy} onclick={reimport}>Re-import…</button>
						{:else if problem.id === 'no_art'}
							Fetch or upload one with the cover buttons above.
						{:else if problem.id === 'unmatched'}
							<button disabled={busy} onclick={reimport}>Re-import…</button>
						{:else if problem.id === 'duplicates' && problem.others}
							{#each problem.others as other, i (other.id)}
								{i ? ', ' : ''}<a href="/albums/{other.id}"
									>{other.albumartist} – {other.album}{other.year ? ` (${other.year})` : ''}</a
								>
							{/each}
						{/if}
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if error}<p class="error">{error}</p>{/if}
	{#if notice}<p class="notice">{notice}</p>{/if}

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
				{#each discs as group (group.disc)}
					<tbody>
						{#if multiDisc}
							<tr class="disc"><th colspan="4">Disc {group.disc}</th></tr>
						{/if}
						{#each group.items as item (item.id)}
							<tr>
								<td class="num"
									><input bind:value={itemForms[item.id].disc} inputmode="numeric" /></td
								>
								<td class="num"
									><input bind:value={itemForms[item.id].track} inputmode="numeric" /></td
								>
								<td><input bind:value={itemForms[item.id].title} /></td>
								<td><input bind:value={itemForms[item.id].artist} /></td>
							</tr>
						{/each}
					</tbody>
				{/each}
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
			{#each discs as group (group.disc)}
				<tbody>
					{#if multiDisc}
						<tr class="disc"><th colspan="4">Disc {group.disc}</th></tr>
					{/if}
					{#each group.items as item (item.id)}
						<tr>
							<td class="num">{item.track || ''}</td>
							<td><a href="/songs/{item.id}">{item.title}</a></td>
							<td>{item.artist}</td>
							<td class="num">{formatLength(item.length)}</td>
						</tr>
					{/each}
				</tbody>
			{/each}
		</table>
	{/if}
{:else if error}
	<p class="error">{error}</p>
{:else}
	<p>Loading…</p>
{/if}

<dialog bind:this={deleteDialog} class="confirm">
	{#if album}
		<h2>Delete {album.album}?</h2>
		<p>
			Removes the album and its {album.items.length} track{album.items.length === 1 ? '' : 's'} from the
			library.
		</p>
		<label>
			<input type="checkbox" bind:checked={deleteFiles} />
			Also delete the files from disk
		</label>
		{#if deleteFiles}
			<p class="danger-note">
				The audio files and the cover in <code>{folder}</code> are deleted, and the folder too if it's
				left empty. This can't be undone.
			</p>
		{:else}
			<p class="meta">The files stay where they are; you can import them again later.</p>
		{/if}
		<div class="buttons end">
			<button type="button" onclick={() => deleteDialog?.close()}>Cancel</button>
			<button type="button" class="primary danger-fill" disabled={busy} onclick={deleteAlbum}>
				{busy ? 'Deleting…' : deleteFiles ? 'Delete album and files' : 'Remove from library'}
			</button>
		</div>
	{/if}
</dialog>

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
	.notice {
		color: var(--ok);
	}
	dialog.confirm {
		width: min(32rem, calc(100vw - 2rem));
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 1.25rem;
		color: inherit;
		background: Canvas;
	}
	dialog.confirm::backdrop {
		background: rgb(0 0 0 / 0.4);
	}
	dialog.confirm h2 {
		margin-top: 0;
		font-size: 1.1em;
		word-break: break-word;
	}
	dialog.confirm label {
		display: flex;
		gap: 0.4rem;
		align-items: center;
	}
	.danger-note {
		color: var(--bad);
		word-break: break-word;
	}
	.buttons.end {
		justify-content: flex-end;
	}
	button.danger-fill {
		background: var(--bad);
		border-color: var(--bad);
		color: white;
	}
	tr.disc th {
		text-align: left;
		font-weight: 600;
		opacity: 1;
		padding-top: 1rem;
		border-bottom: 2px solid color-mix(in srgb, currentColor 15%, transparent);
	}
	tbody:first-of-type tr.disc th {
		padding-top: 0.3rem;
	}
	.problems {
		border: 1px solid color-mix(in srgb, var(--warn) 45%, transparent);
		background: color-mix(in srgb, var(--warn) 8%, transparent);
		border-radius: 6px;
		padding: 0.6rem 0.9rem;
		margin-bottom: 1.25rem;
	}
	.problems ul {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.problems strong {
		color: var(--warn);
	}
	.problems a {
		color: inherit;
	}
	.problems button {
		margin-left: 0.25rem;
		padding: 0.15rem 0.6rem;
	}
	td a {
		color: inherit;
		text-decoration: none;
	}
	td a:hover {
		text-decoration: underline;
	}
	.buttons.art {
		margin-top: 0.5rem;
	}
	.buttons.art + .meta {
		margin-top: 0.4rem;
	}
</style>
