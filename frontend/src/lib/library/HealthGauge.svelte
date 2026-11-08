<script lang="ts">
	import { onMount } from 'svelte';
	import { api, type HealthCheck, type LibraryHealth } from '$lib/api';

	let {
		onupdate,
		onfillcovers,
		onshow
	}: {
		/** Opens the Update library dialog, which fixes missing files. */
		onupdate: () => void;
		/** Opens the Fill missing covers dialog. */
		onfillcovers: () => void;
		/** Shows only the albums failing a check (or any) in the library. */
		onshow: (check: HealthCheck | 'any') => void;
	} = $props();

	function show(check: HealthCheck | 'any') {
		dialog?.close();
		onshow(check);
	}

	let health = $state<LibraryHealth | null>(null);
	let error = $state<string | null>(null);
	let dialog = $state<HTMLDialogElement>();

	onMount(async () => {
		try {
			health = await api.health();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	});

	const score = $derived(
		health ? (health.albums ? Math.floor((health.healthy / health.albums) * 100) : 100) : 0
	);
	const tone = $derived(score >= 90 ? 'ok' : score >= 70 ? 'warn' : 'bad');
	// The ring's circumference for r = 15.9155, so dash lengths read as percentages; an offset
	// of a quarter starts it at 12 o'clock.
	const RING = 100;
	// Long lists are cut short; the counts stay exact.
	const SHOWN = 200;
</script>

{#if health}
	<button
		type="button"
		class="gauge {tone}"
		onclick={() => dialog?.showModal()}
		title="Library health: the share of albums with no problems"
	>
		<svg viewBox="0 0 36 36" aria-hidden="true">
			<circle class="track" cx="18" cy="18" r="15.9155" />
			<circle
				class="value"
				cx="18"
				cy="18"
				r="15.9155"
				stroke-dasharray="{score} {RING - score}"
				stroke-dashoffset="25"
			/>
		</svg>
		<span>{score}% healthy</span>
	</button>
{:else if error}
	<span class="meta" title={error}>Health unavailable</span>
{:else}
	<!-- Shown straight away: the check reads every file, which can take a while. -->
	<button type="button" class="gauge loading" disabled aria-busy="true">
		<svg viewBox="0 0 36 36" aria-hidden="true">
			<circle class="track" cx="18" cy="18" r="15.9155" />
			<circle class="value" cx="18" cy="18" r="15.9155" stroke-dasharray="25 75" />
		</svg>
		<span>Checking health…</span>
	</button>
{/if}

<dialog bind:this={dialog}>
	{#if health}
		<h2>Library health</h2>
		<p>
			<strong class={tone}>{score}%</strong> of albums have no problems ({health.healthy} of
			{health.albums}).
			{#if health.healthy < health.albums}
				<button type="button" onclick={() => show('any')}>Show albums with problems</button>
			{/if}
		</p>
		{#each health.checks as check (check.id)}
			<details class:clean={!check.albums.length}>
				<summary>
					<span class="count {check.albums.length ? tone : 'ok'}">{check.albums.length}</span>
					<span class="label">{check.label}</span>
				</summary>
				<p class="meta">{check.description}</p>
				{#if check.albums.length}
					<button type="button" onclick={() => show(check.id)}>Show in the library</button>
				{/if}
				{#if check.id === 'missing_files' && check.albums.length}
					<button
						type="button"
						onclick={() => {
							dialog?.close();
							onupdate();
						}}>Update library…</button
					>
				{/if}
				{#if check.id === 'no_art' && check.albums.length}
					<button
						type="button"
						onclick={() => {
							dialog?.close();
							onfillcovers();
						}}>Fill missing covers…</button
					>
				{/if}
				<ul>
					{#each check.albums.slice(0, SHOWN) as album (album.id)}
						<li>
							<a href="/albums/{album.id}" onclick={() => dialog?.close()}>
								{album.albumartist} – {album.album}{album.year ? ` (${album.year})` : ''}
							</a>
						</li>
					{/each}
				</ul>
				{#if check.albums.length > SHOWN}
					<p class="meta">and {check.albums.length - SHOWN} more</p>
				{/if}
			</details>
		{/each}
		<div class="buttons">
			<button type="button" onclick={() => dialog?.close()}>Close</button>
		</div>
	{/if}
</dialog>

<style>
	.gauge {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.25rem 0.6rem 0.25rem 0.35rem;
	}
	svg {
		width: 1.6rem;
		height: 1.6rem;
	}
	circle {
		fill: none;
		stroke-width: 4;
	}
	.track {
		stroke: var(--line);
	}
	.value {
		stroke: currentColor;
		stroke-linecap: round;
	}
	.gauge.ok svg,
	.ok {
		color: var(--ok);
	}
	.gauge.warn svg,
	.warn {
		color: var(--warn);
	}
	.gauge.bad svg,
	.bad {
		color: var(--bad);
	}
	.gauge.loading:disabled {
		opacity: 0.75;
		cursor: progress;
	}
	.gauge.loading svg {
		color: var(--accent);
		animation: spin 1s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.gauge.loading svg {
			animation: none;
		}
	}
	.gauge span {
		font-variant-numeric: tabular-nums;
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
	h2 {
		margin-top: 0;
		font-size: 1.1em;
	}
	details {
		border-top: 1px solid var(--line);
		padding: 0.5rem 0;
	}
	details.clean summary {
		opacity: 0.6;
	}
	summary {
		cursor: pointer;
		display: flex;
		gap: 0.75rem;
		align-items: baseline;
	}
	.count {
		min-width: 2.5rem;
		text-align: right;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	ul {
		margin: 0.5rem 0 0;
		padding-left: 3.25rem;
		max-height: 14rem;
		overflow: auto;
		font-size: 0.9em;
	}
	a {
		color: inherit;
	}
	.meta {
		opacity: 0.7;
		font-size: 0.9em;
		margin: 0.4rem 0 0.4rem 3.25rem;
	}
	details > button {
		margin-left: 3.25rem;
	}
	.buttons {
		display: flex;
		justify-content: flex-end;
		margin-top: 1rem;
	}
</style>
