<script lang="ts">
	import { onDestroy } from 'svelte';
	import { api, type ShrinkArt } from '$lib/api';

	let { onclose }: { onclose: () => void } = $props();

	const WIDTHS = [500, 600, 800, 1000, 1200, 1500];
	const QUALITIES = [70, 80, 85, 90, 95];

	let dialog = $state<HTMLDialogElement>();
	let job = $state<ShrinkArt | null>(null);
	let maxWidth = $state(1000);
	let quality = $state(85);
	let error = $state<string | null>(null);
	let timer: ReturnType<typeof setTimeout> | undefined;

	$effect(() => {
		dialog?.showModal();
		poll();
	});

	onDestroy(() => clearTimeout(timer));

	async function poll() {
		try {
			job = await api.shrinkStatus();
			if (job.running) timer = setTimeout(poll, 1000);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	async function start() {
		error = null;
		try {
			job = await api.shrinkArt(maxWidth, quality);
			timer = setTimeout(poll, 500);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}

	function megabytes(bytes = 0) {
		return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
	}
</script>

<dialog bind:this={dialog} {onclose}>
	<h2>Shrink embedded covers</h2>
	<p>
		Re-encodes the cover art inside every track as a JPEG no wider than the size below, so the art
		doesn't bloat your files. Covers already that small (and under 200 KB) are left alone, and a
		track is only rewritten when it gets smaller. The cover files in album folders aren't touched.
	</p>

	{#if job && !job.can_resize}
		<p class="error">Shrinking images needs ImageMagick or Pillow on the server.</p>
	{:else if job?.running}
		<p>
			Working… {job.done} of {job.total} tracks.
			<progress max={job.total} value={job.done}></progress>
		</p>
	{:else if job?.total !== undefined}
		<p>
			Rewrote <strong>{job.rewritten}</strong> of {job.total} tracks, saving
			<strong>{megabytes(job.saved_bytes)}</strong>. {job.unchanged} were already small enough,
			{job.no_art} have no embedded cover{job.failed ? `, ${job.failed} failed (see the log)` : ''}.
		</p>
	{/if}

	{#if error}<p class="error">{error}</p>{/if}

	<div class="buttons">
		{#if job?.can_resize && !job.running}
			<label>
				Max size
				<select bind:value={maxWidth}>
					{#each WIDTHS as w (w)}<option value={w}>{w} px</option>{/each}
				</select>
			</label>
			<label>
				Quality
				<select bind:value={quality}>
					{#each QUALITIES as q (q)}<option value={q}>{q}</option>{/each}
				</select>
			</label>
		{/if}
		<span class="spacer"></span>
		<button type="button" onclick={() => dialog?.close()}>Close</button>
		<button
			type="button"
			class="primary"
			disabled={!job?.can_resize || job.running}
			onclick={start}
		>
			Shrink covers
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
	.error {
		color: crimson;
	}
	.buttons {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-top: 1rem;
	}
	.buttons label {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}
	select {
		font: inherit;
		padding: 0.25rem;
	}
	.spacer {
		flex: 1;
	}
</style>
