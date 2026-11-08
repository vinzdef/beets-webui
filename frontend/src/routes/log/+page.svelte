<script lang="ts">
	import { onMount } from 'svelte';
	import { imports, type LogEntry } from '$lib/api';

	type Filter = 'all' | 'imported' | 'choices' | 'problems';
	const filters: { value: Filter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'imported', label: 'Imported' },
		{ value: 'choices', label: 'Decisions' },
		{ value: 'problems', label: 'Problems' }
	];
	const PAGE = 1000;

	let entries = $state<LogEntry[]>([]);
	let total = $state(0);
	let filter = $state<Filter>('all');
	let text = $state('');
	let loading = $state(false);
	let error = $state<string | null>(null);

	async function load(offset = 0) {
		loading = true;
		error = null;
		try {
			const page = await imports.log(offset, PAGE);
			total = page.total;
			entries = offset ? [...entries, ...page.entries] : page.entries;
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	onMount(() => load());

	function matches(entry: LogEntry): boolean {
		if (filter === 'imported' && entry.kind !== 'imported') return false;
		if (filter === 'choices' && entry.kind !== 'choice') return false;
		if (
			filter === 'problems' &&
			!['warning', 'error'].includes(entry.level ?? '') &&
			!['aborted', 'failed'].includes(entry.kind)
		)
			return false;
		const needle = text.trim().toLowerCase();
		return !needle || entry.message.toLowerCase().includes(needle);
	}

	// Entries come newest first; each import's run of entries becomes one section, headed by its
	// "started" entry and its outcome when those are among the loaded entries.
	const runs = $derived.by(() => {
		const out: { job: string; start?: LogEntry; end?: LogEntry; entries: LogEntry[] }[] = [];
		for (const entry of entries) {
			const job = entry.job ?? '';
			let run = out.at(-1);
			if (run?.job !== job) {
				run = { job, entries: [] };
				out.push(run);
			}
			if (entry.kind === 'started') run.start = entry;
			if (['done', 'aborted', 'failed'].includes(entry.kind)) run.end ??= entry;
			if (matches(entry)) run.entries.push(entry);
		}
		return out.filter((run) => run.entries.length);
	});

	const outcome: Record<string, string> = {
		done: 'Finished',
		aborted: 'Aborted',
		failed: 'Failed'
	};

	function date(t: number) {
		return new Date(t * 1000).toLocaleString();
	}

	function time(t: number) {
		return new Date(t * 1000).toLocaleTimeString();
	}

	function title(run: (typeof runs)[number]) {
		if (!run.start) return 'Import (started earlier: load older entries)';
		const what = (run.start.paths ?? []).map((p) => p.split('/').pop()).join(', ');
		return `${run.start.reimport ? 'Re-import' : 'Import'} of ${what}`;
	}
</script>

<h1>Log</h1>

<div class="toolbar">
	<div class="segmented" role="group" aria-label="Show">
		{#each filters as f (f.value)}
			<button
				type="button"
				class:current={filter === f.value}
				aria-pressed={filter === f.value}
				onclick={() => (filter = f.value)}>{f.label}</button
			>
		{/each}
	</div>
	<input bind:value={text} placeholder="Filter by text" />
	<button type="button" disabled={loading} onclick={() => load()}>Refresh</button>
</div>

{#if error}<p class="error">{error}</p>{/if}

{#if !entries.length && !loading && !error}
	<p class="meta">Nothing logged yet. Every import from now on shows up here.</p>
{:else if !runs.length && entries.length}
	<p class="meta">No entries match.</p>
{/if}

{#each runs as run, i (run.job + i)}
	<section>
		<header>
			<h2>{title(run)}</h2>
			<span class="meta">
				{#if run.start}{date(run.start.time)}{/if}
				{#if run.end}<span class="badge {run.end.kind}">{outcome[run.end.kind]}</span>
				{:else if run.start}<span class="badge">Running or interrupted</span>{/if}
			</span>
		</header>
		<ol class="log">
			{#each run.entries as entry, j (j)}
				<li class="{entry.kind} {entry.level ?? ''}">
					<time>{time(entry.time)}</time>
					{#if entry.album_id}
						<a href="/albums/{entry.album_id}">{entry.message}</a>
					{:else if entry.item_id}
						<a href="/songs/{entry.item_id}">{entry.message}</a>
					{:else}
						<span>{entry.message}</span>
					{/if}
				</li>
			{/each}
		</ol>
	</section>
{/each}

{#if entries.length < total}
	<button class="more" disabled={loading} onclick={() => load(entries.length)}>
		{loading ? 'Loading…' : `Load older entries (${total - entries.length} left)`}
	</button>
{/if}

<style>
	h1 {
		margin-top: 0;
	}
	.toolbar {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: center;
		margin-bottom: 1rem;
	}
	.toolbar input {
		flex: 1;
		min-width: 10rem;
		font: inherit;
		padding: 0.4rem 0.5rem;
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
	section {
		margin-bottom: 1.5rem;
	}
	header {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.25rem 0.75rem;
		border-bottom: 1px solid var(--line);
		padding-bottom: 0.3rem;
		margin-bottom: 0.4rem;
	}
	h2 {
		font-size: 1rem;
		margin: 0;
		word-break: break-word;
	}
	.meta {
		opacity: 0.7;
		font-size: 0.9em;
	}
	.badge {
		margin-left: 0.5rem;
		font-size: 0.85em;
		padding: 0.05rem 0.4rem;
		border-radius: 4px;
		background: var(--subtle);
	}
	.badge.done {
		color: var(--ok);
	}
	.badge.aborted {
		color: var(--warn);
	}
	.badge.failed {
		color: var(--bad);
	}
	.log {
		list-style: none;
		padding: 0;
		margin: 0;
		font-size: 0.9em;
	}
	.log li {
		display: flex;
		gap: 0.75rem;
		padding: 0.15rem 0;
	}
	.log time {
		opacity: 0.5;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}
	.log span,
	.log a {
		min-width: 0;
		word-break: break-word;
	}
	.log a {
		color: inherit;
	}
	.log .imported,
	.log .done {
		color: var(--ok);
	}
	.log .warning,
	.log .aborted {
		color: var(--warn);
	}
	.log .error,
	.log .failed {
		color: var(--bad);
	}
	.error {
		color: crimson;
	}
	.more {
		display: block;
		margin: 1rem auto;
	}
</style>
