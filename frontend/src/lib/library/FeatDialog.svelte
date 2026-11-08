<script lang="ts">
	import { api, type FeatPreview } from '$lib/api';

	let {
		onclose
	}: {
		/** `changed` says whether any tracks were changed. */ onclose: (changed: boolean) => void;
	} = $props();

	let dialog = $state<HTMLDialogElement>();
	let preview = $state<FeatPreview | null>(null);
	// The tracks to change; all of them until you untick some.
	let approved = $state<Set<number>>(new Set());
	let error = $state<string | null>(null);
	let busy = $state(false);
	let done = $state<number | null>(null);

	$effect(() => {
		dialog?.showModal();
		load();
	});

	async function load() {
		error = null;
		try {
			preview = await api.previewFeat();
			approved = new Set(preview.changes.map((c) => c.id));
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	function toggle(id: number) {
		const next = new Set(approved);
		if (!next.delete(id)) next.add(id);
		approved = next;
	}

	async function apply() {
		busy = true;
		error = null;
		try {
			done = (await api.moveFeat([...approved])).changed;
			await load();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	const all = $derived(!!preview?.changes.length && approved.size === preview.changes.length);
</script>

<dialog bind:this={dialog} onclose={() => onclose(!!done)}>
	<h2>Move "feat." into titles</h2>
	<p>
		Tracks whose artist names a guest ("Cypress Hill feat. Eminem") get just the main artist, with
		the guest added to the title instead, so players like Jellyfin list one artist. Untick any you
		want to leave as they are.
	</p>

	{#if done !== null}<p class="notice">Changed {done} track{done === 1 ? '' : 's'}.</p>{/if}
	{#if error}
		<p class="error">{error}</p>
	{:else if !preview}
		<p class="meta">Looking for featured artists…</p>
	{:else if !preview.changes.length}
		<p>No track artists name a featured artist.</p>
	{:else}
		<div class="bar">
			<button
				type="button"
				class="link"
				onclick={() => (approved = all ? new Set() : new Set(preview!.changes.map((c) => c.id)))}
				>{all ? 'Untick all' : 'Tick all'}</button
			>
			<span class="meta">{approved.size} of {preview.changes.length} tracks ticked</span>
		</div>
		<ul class="changes">
			{#each preview.changes as change (change.id)}
				<li>
					<label>
						<input
							type="checkbox"
							checked={approved.has(change.id)}
							onchange={() => toggle(change.id)}
						/>
						<span>
							<span class="row"
								><span class="old">{change.artist}</span> →
								<strong>{change.new_artist}</strong></span
							>
							{#if change.new_title !== change.title}
								<span class="row"
									><span class="old">{change.title}</span> →
									<strong>{change.new_title}</strong></span
								>
							{/if}
							{#if change.album}
								<span class="meta"
									>{#if change.album_id}<a
											href="/albums/{change.album_id}"
											onclick={() => dialog?.close()}>{change.album}</a
										>{:else}{change.album}{/if}</span
								>
							{/if}
						</span>
					</label>
				</li>
			{/each}
		</ul>
		<p class="meta">
			Changes are written to the files{preview.moves_files
				? ', and files are renamed to match their new titles'
				: ''}.
		</p>
	{/if}

	<div class="buttons">
		<button type="button" onclick={() => dialog?.close()}>Close</button>
		<button type="button" class="primary" disabled={busy || !approved.size} onclick={apply}>
			{busy ? 'Changing…' : `Change ${approved.size} track${approved.size === 1 ? '' : 's'}`}
		</button>
	</div>
</dialog>

<style>
	dialog {
		width: min(42rem, calc(100vw - 2rem));
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
	.bar {
		display: flex;
		gap: 1rem;
		align-items: baseline;
		margin-bottom: 0.4rem;
	}
	.changes {
		list-style: none;
		margin: 0;
		padding: 0;
		max-height: 22rem;
		overflow: auto;
		border: 1px solid var(--line);
		border-radius: 6px;
	}
	.changes li + li {
		border-top: 1px solid var(--line);
	}
	.changes label {
		display: flex;
		gap: 0.6rem;
		align-items: flex-start;
		padding: 0.45rem 0.6rem;
		cursor: pointer;
	}
	.changes label > span {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
		min-width: 0;
	}
	.row {
		word-break: break-word;
	}
	.old {
		opacity: 0.6;
		text-decoration: line-through;
	}
	.meta {
		opacity: 0.7;
		font-size: 0.9em;
	}
	a {
		color: inherit;
	}
	button.link {
		background: none;
		border: none;
		padding: 0;
		color: var(--accent);
	}
	.notice {
		color: var(--ok);
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
