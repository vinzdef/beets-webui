<script lang="ts">
	import { onMount } from 'svelte';
	import { imports, type AnswerBody, type ImportJob, type ImportMode, type Inbox } from '$lib/api';
	import MatchQuestion from '$lib/import/MatchQuestion.svelte';
	import OtherQuestion from '$lib/import/OtherQuestion.svelte';

	let job = $state<ImportJob | null>(null);
	let inboxes = $state<Inbox[]>([]);
	let selected = $state<string[]>([]);
	// The entry last clicked, as the anchor for shift-click range selection.
	let anchor: string | null = null;
	const MODE_KEY = 'beets-webui.import.mode';
	let mode = $state<ImportMode>(loadMode());
	let singletons = $state(false);
	let groupAlbums = $state(false);
	let error = $state<string | null>(null);
	let busy = $state(false);

	$effect(() => {
		try {
			localStorage.setItem(MODE_KEY, mode);
		} catch {
			// Storage can be unavailable (private windows); the default is fine then.
		}
	});

	function loadMode(): ImportMode {
		try {
			const saved = localStorage.getItem(MODE_KEY);
			if (saved === 'auto' || saved === 'manual' || saved === 'timid') return saved;
			// Names used before the modes were renamed.
			const legacy = localStorage.getItem('beets-webui.import.ask');
			const renamed = { exact: 'manual', config: 'auto', always: 'timid' } as const;
			if (legacy && legacy in renamed) return renamed[legacy as keyof typeof renamed];
		} catch {
			// See above.
		}
		return 'manual';
	}

	const allPaths = $derived(inboxes.flatMap((i) => i.entries.map((e) => e.path)));
	const allSelected = $derived(allPaths.length > 0 && allPaths.every((p) => selected.includes(p)));

	function toggleAll() {
		selected = allSelected ? [] : [...allPaths];
		anchor = null;
	}

	/** Toggle one entry, or with Shift every entry from the previous click to this one. */
	function clickEntry(event: MouseEvent, path: string) {
		const checked = (event.currentTarget as HTMLInputElement).checked;
		let paths = [path];
		if (event.shiftKey && anchor && allPaths.includes(anchor)) {
			const [from, to] = [allPaths.indexOf(anchor), allPaths.indexOf(path)].sort((a, b) => a - b);
			paths = allPaths.slice(from, to + 1);
		}
		const next = new Set(selected);
		for (const p of paths) {
			if (checked) next.add(p);
			else next.delete(p);
		}
		// Keep the list's order, which is also the order albums are imported in.
		selected = allPaths.filter((p) => next.has(p));
		anchor = path;
	}

	const active = $derived(job?.status === 'running' || job?.status === 'waiting');

	onMount(() => {
		loadInbox();
		return imports.subscribe((j) => {
			// Refresh the inbox when an import finishes: files may have moved.
			if (j && !isActive(j) && job && isActive(job)) loadInbox();
			job = j;
		});
	});

	function jobLabel(j: ImportJob) {
		if (j.reimport) return `Re-importing ${j.paths.join(', ')}`;
		return j.paths.map((p) => p.split('/').pop()).join(', ');
	}

	function isActive(j: ImportJob) {
		return j.status === 'running' || j.status === 'waiting';
	}

	async function loadInbox() {
		try {
			inboxes = (await imports.inboxes()).inboxes;
			const paths = new Set(inboxes.flatMap((i) => i.entries.map((e) => e.path)));
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
			mode,
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
		<span class="paths">{jobLabel(job)}</span>
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
			<span class="paths">{jobLabel(job)}</span>
		</div>
		{#if job.error}<p class="error">{job.error}</p>{/if}
	{/if}

	<section class="picker">
		{#if inboxes.length === 0}
			<p>
				No inboxes are configured. Add named folders to your beets config:
				<code>webui: &#123;inboxes: &#123;Downloads: ~/Downloads&#125;&#125;</code>
			</p>
		{/if}
		{#if allPaths.length}
			<div class="select-bar">
				<button class="link" onclick={toggleAll}>
					{allSelected ? 'Clear selection' : 'Select all'}
				</button>
				<span class="meta">
					{selected.length} of {allPaths.length} selected · Shift-click to select a range
				</span>
			</div>
		{/if}
		{#each inboxes as inbox (inbox.name)}
			<h2>{inbox.name} <span class="folder">{inbox.path}</span></h2>
			{#if !inbox.exists}
				<p class="error">This folder doesn't exist.</p>
			{:else if inbox.entries.length === 0}
				<p class="meta">Empty. Put albums here to import them.</p>
			{:else}
				<ul>
					{#each inbox.entries as entry (entry.path)}
						<li>
							<label>
								<input
									type="checkbox"
									checked={selected.includes(entry.path)}
									onclick={(e) => clickEntry(e, entry.path)}
								/>
								<span>{entry.is_dir ? '📁' : '🎵'} {entry.name}</span>
							</label>
						</li>
					{/each}
				</ul>
			{/if}
		{/each}

		{#if inboxes.length}
			<fieldset>
				<legend>Mode</legend>
				<label>
					<input type="radio" value="auto" bind:group={mode} />
					<span
						><strong>Auto</strong> · matches above the strong-match threshold in your beets config are
						applied automatically</span
					>
				</label>
				<label>
					<input type="radio" value="manual" bind:group={mode} />
					<span><strong>Manual</strong> · approve every match that isn't 100%</span>
				</label>
				<label>
					<input type="radio" value="timid" bind:group={mode} />
					<span><strong>Timid</strong> · approve every match</span>
				</label>
			</fieldset>
			<fieldset>
				<label>
					<input type="checkbox" bind:checked={singletons} />
					<span>
						<strong>Import as individual tracks</strong>
						<small>
							Match each file on its own against single recordings instead of treating each folder
							as an album. For loose songs that don't belong to an album.
						</small>
					</span>
				</label>
				<label>
					<input type="checkbox" bind:checked={groupAlbums} />
					<span>
						<strong>Split folders into albums by tags</strong>
						<small>
							Normally one folder is one album. This splits a folder that mixes several albums into
							one album per artist and album tag before matching.
						</small>
					</span>
				</label>
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
		<h2>Log <a class="full" href="/log">Full log</a></h2>
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
	}
	.folder {
		font-weight: normal;
		font-size: 0.85em;
		opacity: 0.55;
		margin-left: 0.5rem;
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
		/* Shift-clicking would otherwise select the text between the clicks. */
		user-select: none;
	}
	.select-bar {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.25rem 1rem;
		margin-top: 0.5rem;
	}
	button.link {
		background: none;
		border: none;
		padding: 0;
		color: var(--accent);
	}
	fieldset label {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
	}
	fieldset small {
		display: block;
		opacity: 0.65;
	}
	legend {
		padding: 0;
		margin-bottom: 0.35rem;
		font-weight: 500;
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
	h2 .full {
		font-weight: normal;
		font-size: 0.85em;
		margin-left: 0.5rem;
		color: inherit;
		opacity: 0.7;
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
