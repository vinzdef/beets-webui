<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { player } from '$lib/player.svelte';
	import { api, fieldText as text, formatLength, imports, type Item } from '$lib/api';

	// A track on an album takes the album's fields from it; those are edited on the album page.
	const trackFields: { key: string; label: string; hint?: string }[] = [
		{ key: 'title', label: 'Title' },
		{ key: 'artist', label: 'Artist' },
		{ key: 'track', label: 'Track' },
		{ key: 'disc', label: 'Disc' }
	];
	const singletonFields = [
		...trackFields,
		{ key: 'album', label: 'Album' },
		{ key: 'albumartist', label: 'Album artist' },
		{ key: 'year', label: 'Year' },
		{ key: 'genres', label: 'Genres', hint: 'Separate with ;' }
	];

	let item = $state<(Item & { can_refresh?: boolean }) | null>(null);
	let notice = $state<string | null>(null);
	let error = $state<string | null>(null);
	let editing = $state(false);
	let busy = $state(false);
	let form = $state<Record<string, string>>({});

	const albumId = $derived(item?.album_id as number | null | undefined);
	const fields = $derived(albumId == null ? singletonFields : trackFields);

	$effect(() => {
		const id = Number(page.params.id);
		item = null;
		error = null;
		editing = false;
		api.item(id).then(
			(i) => (item = i),
			(e) => (error = e instanceof Error ? e.message : String(e))
		);
	});

	function startEditing() {
		form = Object.fromEntries(fields.map((f) => [f.key, text(item![f.key])]));
		error = null;
		editing = true;
	}

	async function save() {
		const changed = Object.fromEntries(
			fields.filter((f) => form[f.key] !== text(item![f.key])).map((f) => [f.key, form[f.key]])
		);
		if (!Object.keys(changed).length) {
			editing = false;
			return;
		}
		busy = true;
		error = null;
		try {
			item = await api.editItem(item!.id, changed);
			editing = false;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	async function refresh() {
		const ok = confirm(
			"Fetch this recording from MusicBrainz again and apply its current data? Tags MusicBrainz provides replace yours, including edits you've made to them."
		);
		if (!ok) return;
		busy = true;
		error = null;
		notice = null;
		try {
			item = await api.refreshItem(item!.id);
			notice = 'Refreshed from MusicBrainz.';
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
			await imports.reimportItem(item!.id, { mode: 'timid' });
			await goto('/import');
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			busy = false;
		}
	}

	const details = $derived(
		item
			? [
					['Length', formatLength(item.length)],
					['Year', text(item.year)],
					['Genres', text(item.genres)],
					[
						'Format',
						[item.format, item.bitrate ? `${Math.round(Number(item.bitrate) / 1000)} kbps` : '']
							.filter(Boolean)
							.join(' · ')
					],
					['File', item.path ?? '']
				].filter(([, value]) => value)
			: []
	);
</script>

{#if item}
	<header>
		<div class="cover">
			<img src={api.itemArtUrl(item.id)} alt="" onerror={(e) => e.currentTarget.remove()} />
		</div>
		<div class="heading">
			<h1>{item.title || 'Untitled'}</h1>
			<p>
				{#if item.artist}<a href="/artist?{new URLSearchParams({ name: item.artist })}"
						>{item.artist}</a
					>{/if}
			</p>
			<p class="meta">
				{#if albumId != null}
					<a href="/albums/{albumId}">{item.album}</a>{item.track ? ` · track ${item.track}` : ''}
				{:else}
					Single track{item.album ? ` · ${item.album}` : ''}
				{/if}
			</p>
			{#if !editing}
				<div class="buttons">
					<button class="primary" onclick={() => player.playOrToggle(item!.id, [item!], 0)}
						>{player.current?.id === item.id && player.playing ? '❚❚ Pause' : '▶ Play'}</button
					>
					<button onclick={startEditing}>Edit</button>
					{#if albumId == null}
						<button
							disabled={busy}
							onclick={reimport}
							title="Look up matches for this track again and choose one. Nothing is copied; the file is renamed only if the new tags change its path"
							>Re-import…</button
						>
					{/if}
					{#if item.can_refresh}
						<button
							disabled={busy}
							onclick={refresh}
							title="Fetch the recording this track is matched to again, for corrections made on MusicBrainz since you imported it"
							>Refresh from MusicBrainz</button
						>
					{/if}
				</div>
			{/if}
		</div>
	</header>

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
				{#each fields as f (f.key)}
					<label>
						<span>{f.label}</span>
						<input bind:value={form[f.key]} placeholder={f.hint} />
					</label>
				{/each}
			</div>
			<p class="meta">
				{#if albumId != null}
					Album, year and genres come from the album: <a href="/albums/{albumId}">edit them there</a
					>.
				{/if}
				Saving writes the tags to the file and, if your import settings move or copy files, renames it
				to match.
			</p>
			<div class="buttons end">
				<button type="button" disabled={busy} onclick={() => (editing = false)}>Cancel</button>
				<button class="primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
			</div>
		</form>
	{:else}
		<dl>
			{#each details as [label, value] (label)}
				<dt>{label}</dt>
				<dd>{value}</dd>
			{/each}
		</dl>
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
		opacity: 0.7;
		font-size: 0.9em;
	}
	a {
		color: inherit;
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-top: 0.75rem;
	}
	.buttons.end {
		justify-content: flex-end;
	}
	.fields {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
		gap: 0.75rem;
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
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.4rem 1.25rem;
		margin: 0;
	}
	dt {
		opacity: 0.6;
	}
	dd {
		margin: 0;
		word-break: break-word;
	}
	.error {
		color: crimson;
	}
	.notice {
		color: var(--ok);
	}
</style>
