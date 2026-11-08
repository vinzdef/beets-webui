<script lang="ts">
	import { api } from '$lib/api';

	let {
		kind,
		ids,
		onclose
	}: {
		kind: 'albums' | 'songs';
		ids: number[];
		/** Called when the dialog closes; `saved` says whether anything changed. */
		onclose: (saved: boolean) => void;
	} = $props();

	const fields = $derived(
		kind === 'albums'
			? [
					{ key: 'albumartist', label: 'Album artist' },
					{ key: 'album', label: 'Album' },
					{ key: 'year', label: 'Year' },
					{ key: 'genres', label: 'Genres', hint: 'Separate with ;' },
					{ key: 'label', label: 'Label' },
					{ key: 'catalognum', label: 'Catalog number' },
					{ key: 'country', label: 'Country' }
				]
			: [
					{ key: 'artist', label: 'Artist' },
					{ key: 'albumartist', label: 'Album artist' },
					{ key: 'album', label: 'Album' },
					{ key: 'year', label: 'Year' },
					{ key: 'genres', label: 'Genres', hint: 'Separate with ;' }
				]
	);

	let dialog = $state<HTMLDialogElement>();
	let values = $state<Record<string, string>>({});
	// Which fields to set: typing ticks a field, and a ticked empty field clears it.
	let enabled = $state<Record<string, boolean>>({});
	let busy = $state(false);
	let error = $state<string | null>(null);
	let saved = false;

	const noun = $derived(
		`${ids.length} ${kind === 'albums' ? 'album' : 'song'}${ids.length === 1 ? '' : 's'}`
	);
	const chosen = $derived(fields.filter((f) => enabled[f.key]));

	$effect(() => {
		dialog?.showModal();
	});

	async function save() {
		busy = true;
		error = null;
		try {
			const changes = Object.fromEntries(chosen.map((f) => [f.key, values[f.key] ?? '']));
			await (kind === 'albums' ? api.editAlbums(ids, changes) : api.editItems(ids, changes));
			saved = true;
			dialog?.close();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<dialog bind:this={dialog} onclose={() => onclose(saved)}>
	<h2>Edit {noun}</h2>
	<p class="meta">
		Ticked fields are set to the same value on all of them; the rest stay as they are.
		{#if kind === 'songs'}
			Album fields reach an album once all of its tracks have the same value.
		{/if}
	</p>
	<form
		onsubmit={(e) => {
			e.preventDefault();
			save();
		}}
	>
		{#each fields as f (f.key)}
			<label class="row">
				<input type="checkbox" bind:checked={enabled[f.key]} aria-label="Set {f.label}" />
				<span>{f.label}</span>
				<input
					bind:value={values[f.key]}
					placeholder={f.hint}
					oninput={() => (enabled[f.key] = true)}
				/>
			</label>
		{/each}
		<p class="meta">
			Saving writes the tags to the files and, if your import settings move or copy files, renames
			them to match.
		</p>
		{#if error}<p class="error">{error}</p>{/if}
		<div class="buttons">
			<button type="button" onclick={() => dialog?.close()}>Cancel</button>
			<button class="primary" disabled={busy || !chosen.length}>
				{busy ? 'Saving…' : `Save ${noun}`}
			</button>
		</div>
	</form>
</dialog>

<style>
	dialog {
		width: min(32rem, calc(100vw - 2rem));
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
	h2 {
		margin-top: 0;
		font-size: 1.1em;
	}
	.row {
		display: grid;
		grid-template-columns: auto 8rem 1fr;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
	}
	.row input:not([type='checkbox']) {
		font: inherit;
		padding: 0.35rem 0.5rem;
		min-width: 0;
	}
	.meta {
		opacity: 0.7;
		font-size: 0.9em;
	}
	.error {
		color: crimson;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		margin-top: 1rem;
	}
</style>
