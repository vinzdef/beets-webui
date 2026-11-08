<script lang="ts">
	import { onDestroy } from 'svelte';
	import { api, type CoverFill } from '$lib/api';

	let {
		onclose
	}: {
		/** Called when the dialog closes; `filled` says whether any covers were added. */ onclose: (
			filled: boolean
		) => void;
	} = $props();

	let dialog = $state<HTMLDialogElement>();
	let fill = $state<CoverFill | null>(null);
	let fetchOnline = $state(true);
	let error = $state<string | null>(null);
	let timer: ReturnType<typeof setTimeout> | undefined;
	let started = false;

	$effect(() => {
		dialog?.showModal();
		poll();
	});

	onDestroy(() => clearTimeout(timer));

	async function poll() {
		try {
			fill = await api.coverFill();
			if (fill.running) timer = setTimeout(poll, 1000);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function start() {
		error = null;
		started = true;
		try {
			fill = await api.fillCovers(fetchOnline && !!fill?.can_fetch);
			timer = setTimeout(poll, 500);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	const filled = $derived((fill?.folder ?? 0) + (fill?.embedded ?? 0) + (fill?.fetched ?? 0));
	// Long lists are cut short; the count stays exact.
	const SHOWN = 200;
</script>

<dialog bind:this={dialog} onclose={() => onclose(started && filled > 0)}>
	<h2>Fill missing covers</h2>
	<p>
		Gives every album without a cover file one in its folder, named <code>cover.jpg</code> (or
		<code>.png</code>, as the image is; your <code>art_filename</code> setting can change the name).
		It uses, in order: an image already in the album's folder, art embedded in its tracks, and
		{fill?.can_fetch ? "fetchart's online sources" : 'nothing online (fetchart is off)'}.
	</p>

	{#if fill?.running}
		<p>
			Working… {fill.done} of {fill.total} albums.
			<progress max={fill.total} value={fill.done}></progress>
		</p>
	{:else if fill?.total !== undefined}
		<p>
			{#if fill.total === 0}
				Every album already has a cover file.
			{:else}
				Added <strong>{filled}</strong> of {fill.total}: {fill.folder} from folder images,
				{fill.embedded} from embedded art, {fill.fetched} fetched online.
			{/if}
		</p>
		{#if fill.not_found?.length}
			<p class="meta">
				No cover found for {fill.not_found.length}; upload one on the album's page:
			</p>
			<ul>
				{#each fill.not_found.slice(0, SHOWN) as album (album.id)}
					<li>
						<a href="/albums/{album.id}" onclick={() => dialog?.close()}
							>{album.albumartist} – {album.album}</a
						>
					</li>
				{/each}
			</ul>
			{#if fill.not_found.length > SHOWN}
				<p class="meta">and {fill.not_found.length - SHOWN} more</p>
			{/if}
		{/if}
	{/if}

	{#if error}<p class="error">{error}</p>{/if}

	<div class="buttons">
		{#if fill?.can_fetch && !fill.running}
			<label>
				<input type="checkbox" bind:checked={fetchOnline} />
				Look online too
			</label>
		{/if}
		<button type="button" onclick={() => dialog?.close()}>Close</button>
		<button type="button" class="primary" disabled={!fill || fill.running} onclick={start}>
			{fill?.total !== undefined && !fill.running ? 'Run again' : 'Fill missing covers'}
		</button>
	</div>
</dialog>

<style>
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
	h2 {
		margin-top: 0;
		font-size: 1.1em;
	}
	progress {
		width: 100%;
		margin-top: 0.4rem;
	}
	ul {
		max-height: 14rem;
		overflow: auto;
		margin: 0;
		font-size: 0.9em;
	}
	a {
		color: inherit;
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
		align-items: center;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-top: 1rem;
	}
	.buttons label {
		margin-right: auto;
		display: inline-flex;
		gap: 0.35rem;
		align-items: center;
	}
</style>
