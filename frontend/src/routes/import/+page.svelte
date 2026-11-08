<script lang="ts">
	import { onMount } from 'svelte';
	import { imports, type AnswerBody, type ImportJob, type InboxRoot } from '$lib/api';
	import MatchQuestion from '$lib/import/MatchQuestion.svelte';
	import OtherQuestion from '$lib/import/OtherQuestion.svelte';

	let job = $state<ImportJob | null>(null);
	let roots = $state<InboxRoot[]>([]);
	let selected = $state<string[]>([]);
	let timid = $state(false);
	let singletons = $state(false);
	let groupAlbums = $state(false);
	let error = $state<string | null>(null);
	let busy = $state(false);

	const active = $derived(job?.status === 'running' || job?.status === 'waiting');

	onMount(() => {
		loadInbox();
		return imports.subscribe((j) => {
			// Refresh the inbox when an import finishes: files may have moved.
			if (j && !isActive(j) && job && isActive(job)) loadInbox();
			job = j;
		});
	});

	function isActive(j: ImportJob) {
		return j.status === 'running' || j.status === 'waiting';
	}

	async function loadInbox() {
		try {
			roots = (await imports.inbox()).roots;
			const paths = new Set(roots.flatMap((r) => r.entries.map((e) => e.path)));
			selected = selected.filter((p) => paths.has(p));
		} catch (e) {
			error = String(e);
		}
	}

	async function run<T>(action: () => Promise<T>) {
		error = null;
		busy = true;
		try {
			await action();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}

	function start() {
		// Unchecked options are left out so the beets config decides.
		const options = {
			...(timid && { timid: true }),
			...(singletons && { singletons: true }),
			...(groupAlbums && { group_albums: true })
		};
		run(() => imports.start(selected, options));
	}

	function answer(body: AnswerBody) {
		if (job?.question) {
			const id = job.question.id;
			run(() => imports.answer(id, body));
		}
	}

	function time(t: number) {
		return new Date(t * 1000).toLocaleTimeString();
	}

	const statusText: Record<ImportJob['status'], string> = {
		running: 'Working…',
		waiting: 'Waiting for you',
		done: 'Finished',
		aborted: 'Aborted',
		failed: 'Failed'
	};
</script>

<h1>Import</h1>

{#if error}<p class="error">{error}</p>{/if}

{#if job && active}
	<div class="status">
		<span class="badge {job.status}">{statusText[job.status]}</span>
		<span class="paths">{job.paths.map((p) => p.split('/').pop()).join(', ')}</span>
		<button class="danger" disabled={busy} onclick={() => run(imports.abort)}>Abort</button>
	</div>

	{#if job.question?.kind === 'match'}
		{#key job.question.id}
			<MatchQuestion question={job.question} onanswer={answer} />
		{/key}
	{:else if job.question}
		<OtherQuestion question={job.question} onanswer={answer} />
	{:else}
		<p class="working">Looking up matches…</p>
	{/if}
{:else}
	{#if job}
		<div class="status">
			<span class="badge {job.status}">{statusText[job.status]}</span>
			<span class="paths">{job.paths.map((p) => p.split('/').pop()).join(', ')}</span>
		</div>
		{#if job.error}<p class="error">{job.error}</p>{/if}
	{/if}

	<section class="picker">
		{#if roots.length === 0}
			<p>
				No inbox folders are configured. Add them to your beets config:
				<code>webui: inbox: [/path/to/inbox]</code>
			</p>
		{/if}
		{#each roots as root (root.path)}
			<h2>{root.path}</h2>
			{#if !root.exists}
				<p class="error">This folder doesn't exist.</p>
			{:else if root.entries.length === 0}
				<p class="meta">Empty. Put albums here to import them.</p>
			{:else}
				<ul>
					{#each root.entries as entry (entry.path)}
						<li>
							<label>
								<input type="checkbox" value={entry.path} bind:group={selected} />
								<span>{entry.is_dir ? '📁' : '🎵'} {entry.name}</span>
							</label>
						</li>
					{/each}
				</ul>
			{/if}
		{/each}

		{#if roots.length}
			<fieldset>
				<label><input type="checkbox" bind:checked={timid} /> Confirm every match (timid)</label>
				<label
					><input type="checkbox" bind:checked={singletons} /> Import as individual tracks</label
				>
				<label><input type="checkbox" bind:checked={groupAlbums} /> Group albums by tags</label>
			</fieldset>
			<div class="row">
				<button class="primary" disabled={busy || selected.length === 0} onclick={start}>
					Import {selected.length || ''} selected
				</button>
				<button disabled={busy} onclick={loadInbox}>Refresh</button>
			</div>
		{/if}
	</section>
{/if}

{#if job?.log.length}
	<section>
		<h2>Log</h2>
		<ol class="log">
			{#each job.log.toReversed() as entry}
				<li class="{entry.kind} {entry.level ?? ''}">
					<time>{time(entry.time)}</time>
					{#if entry.album_id}
						<a href="/albums/{entry.album_id}">{entry.message}</a>
					{:else}
						<span>{entry.message}</span>
					{/if}
				</li>
			{/each}
		</ol>
	</section>
{/if}

<style>
	h1 {
		margin-top: 0;
	}
	h2 {
		font-size: 1rem;
		margin: 1.5rem 0 0.5rem;
		word-break: break-all;
	}
	.status {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin-bottom: 1.25rem;
	}
	.paths {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.status .danger {
		margin-left: auto;
	}
	.badge {
		padding: 0.15rem 0.6rem;
		border-radius: 999px;
		font-size: 0.85em;
		font-weight: 600;
		background: var(--subtle);
		white-space: nowrap;
	}
	.badge.waiting {
		color: var(--accent);
	}
	.badge.done {
		color: var(--ok);
	}
	.badge.aborted,
	.badge.failed {
		color: var(--bad);
	}
	.working,
	.meta {
		opacity: 0.7;
	}
	.picker ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.picker li label {
		display: flex;
		gap: 0.5rem;
		padding: 0.35rem 0;
		border-bottom: 1px solid var(--line);
		cursor: pointer;
	}
	fieldset {
		border: none;
		padding: 0;
		margin: 1rem 0;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}
	.row {
		display: flex;
		gap: 0.5rem;
	}
	.error {
		color: var(--bad);
	}
	.log {
		list-style: none;
		padding: 0;
		margin: 0;
		font-size: 0.9em;
		max-height: 24rem;
		overflow-y: auto;
	}
	.log li {
		display: flex;
		gap: 0.75rem;
		padding: 0.2rem 0;
	}
	.log time {
		opacity: 0.5;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
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
</style>
