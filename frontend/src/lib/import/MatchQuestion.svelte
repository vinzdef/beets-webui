<script lang="ts">
	import { formatLength, type AnswerBody, type Candidate, type MatchQuestion } from '$lib/api';

	let { question, onanswer }: { question: MatchQuestion; onanswer: (body: AnswerBody) => void } =
		$props();

	let open = $state<boolean[]>([]);
	let searchArtist = $state('');
	let searchName = $state('');
	let searchIds = $state('');

	// A new question (e.g. after a search) starts with only its best candidate expanded.
	$effect(() => {
		open = question.candidates.map((_, i) => i === 0);
	});

	const task = $derived(question.task);
	const best = $derived<Candidate | undefined>(question.candidates[0]);
	const isAlbum = $derived(task.kind === 'album');
	const actions = $derived(question.choices.filter((c) => c.short !== 'b'));
	const canAbort = $derived(question.choices.some((c) => c.short === 'b'));
	const allOpen = $derived(open.length > 0 && open.every(Boolean));

	const labels: Record<string, string> = {
		s: 'Skip',
		u: 'Use as-is',
		t: 'Import as tracks',
		g: 'Group albums',
		r: 'Rescan folder'
	};

	function meta(c: Candidate): string {
		return [c.year, c.label, c.country, c.media, c.albumtype, c.data_source, !isAlbum && c.album]
			.filter((v) => v)
			.join(' · ');
	}

	function changed(a: string | null | undefined, b: string | null | undefined) {
		return (a ?? '').trim().toLowerCase() !== (b ?? '').trim().toLowerCase();
	}

	function apply(index: number) {
		onanswer({ type: 'apply', candidate: index });
	}
</script>

<section class="question">
	<header>
		<p class="eyebrow">
			{isAlbum ? 'Album' : 'Track'} · {task.items.length} file{task.items.length === 1 ? '' : 's'}
		</p>
		<h2>{task.artist || 'Unknown artist'} – {task.name || 'Unknown'}</h2>
		<p class="path">{task.paths.join(', ')}</p>
	</header>

	<div class="toolbar">
		{#if best}
			<button class="primary" onclick={() => apply(0)}>
				Apply {best.similarity.toFixed(0)}% match
			</button>
		{/if}
		{#each actions as choice (choice.short)}
			<button onclick={() => onanswer({ type: 'choice', short: choice.short })}>
				{labels[choice.short] ?? choice.long}
			</button>
		{/each}
		{#if canAbort}
			<button class="danger" onclick={() => onanswer({ type: 'choice', short: 'b' })}>
				Abort import
			</button>
		{/if}
	</div>

	<div class="lookup">
		<form
			onsubmit={(e) => {
				e.preventDefault();
				onanswer({ type: 'search', artist: searchArtist, name: searchName });
			}}
		>
			<input bind:value={searchArtist} placeholder="Artist" aria-label="Artist" />
			<input
				bind:value={searchName}
				placeholder={isAlbum ? 'Album' : 'Title'}
				aria-label={isAlbum ? 'Album' : 'Title'}
			/>
			<button>Search</button>
		</form>
		<form
			onsubmit={(e) => {
				e.preventDefault();
				onanswer({ type: 'id', ids: searchIds });
			}}
		>
			<input bind:value={searchIds} placeholder="MusicBrainz ID or URL" aria-label="ID" />
			<button>Look up</button>
		</form>
	</div>

	{#if question.candidates.length === 0}
		<p class="empty">No matches found. Search by name or ID above, or choose what to do.</p>
	{:else}
		<div class="list-header">
			<span
				>{question.candidates.length} candidate{question.candidates.length === 1 ? '' : 's'}</span
			>
			<button class="link" onclick={() => (open = open.map(() => !allOpen))}>
				{allOpen ? 'Collapse all' : 'Expand all'}
			</button>
		</div>

		<ol class="candidates">
			{#each question.candidates as c, i (c.index)}
				<li class:open={open[i]}>
					<div class="entry-head">
						<button
							class="toggle"
							aria-expanded={open[i]}
							aria-controls="candidate-{question.id}-{i}"
							onclick={() => (open[i] = !open[i])}
						>
							<span class="chevron" aria-hidden="true">▸</span>
							<span class="score {c.strength}">{c.similarity.toFixed(1)}%</span>
							<span class="title">{c.artist} – {c.name}</span>
							{#if meta(c)}<span class="meta">{meta(c)}</span>{/if}
							{#if c.penalties.length}
								<span class="penalties">≠ {c.penalties.join(', ')}</span>
							{/if}
						</button>
						<button class:primary={i === 0} onclick={() => apply(i)}>Apply</button>
					</div>

					{#if open[i]}
						<div class="entry-body" id="candidate-{question.id}-{i}">
							{#if isAlbum && c.tracks}
								<table>
									<thead>
										<tr><th>#</th><th>Your file</th><th></th><th>Match</th><th>Length</th></tr>
									</thead>
									<tbody>
										{#each c.tracks as { item, track }}
											<tr>
												<td class="num">{track.medium_index ?? track.index}</td>
												<td>{item.title || item.path.split('/').pop()}</td>
												<td class="arrow">→</td>
												<td class:changed={changed(item.title, track.title)}>{track.title}</td>
												<td class="num">{formatLength(track.length)}</td>
											</tr>
										{/each}
									</tbody>
								</table>
								{#if c.extra_tracks?.length}
									<p class="warn">
										Missing tracks: {c.extra_tracks.map((t) => t.title).join(', ')}
									</p>
								{/if}
								{#if c.extra_items?.length}
									<p class="warn">
										Unmatched files: {c.extra_items.map((it) => it.title || it.path).join(', ')}
									</p>
								{/if}
							{:else}
								<dl>
									<dt>Your file</dt>
									<dd>{task.items[0]?.title} ({formatLength(task.items[0]?.length)})</dd>
									<dt>Match</dt>
									<dd>{c.name} ({formatLength(c.length)})</dd>
								</dl>
							{/if}
							{#if c.disambig}<p class="meta">{c.disambig}</p>{/if}
						</div>
					{/if}
				</li>
			{/each}
		</ol>
	{/if}
</section>

<style>
	.question {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		min-width: 0;
	}
	h2 {
		margin: 0;
	}
	.eyebrow,
	.path,
	.meta {
		margin: 0;
		opacity: 0.65;
		font-size: 0.9em;
	}
	.path {
		word-break: break-all;
	}
	/* One line of actions; scrolls sideways on narrow screens rather than wrapping. */
	.toolbar {
		display: flex;
		gap: 0.5rem;
		overflow-x: auto;
		padding-bottom: 2px;
	}
	.toolbar button {
		flex-shrink: 0;
		white-space: nowrap;
	}
	.toolbar .danger {
		margin-left: auto;
	}
	.lookup {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem 1.5rem;
	}
	.lookup form {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.list-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 1rem;
		opacity: 0.8;
	}
	button.link {
		background: none;
		border: none;
		padding: 0;
		color: var(--accent);
	}
	.candidates {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.candidates li {
		border: 1px solid var(--line);
		border-radius: 8px;
	}
	.entry-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.35rem 0.5rem 0.35rem 0;
	}
	.toggle {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		background: none;
		border: none;
		text-align: left;
		white-space: nowrap;
		overflow: hidden;
	}
	.toggle > span {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.chevron {
		display: inline-block;
		flex-shrink: 0;
		transition: transform 0.15s;
		opacity: 0.6;
	}
	li.open .chevron {
		transform: rotate(90deg);
	}
	.score {
		flex-shrink: 0;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.strong {
		color: var(--ok);
	}
	.medium {
		color: var(--warn);
	}
	.weak {
		color: var(--bad);
	}
	.title {
		flex-shrink: 0;
		max-width: 60%;
		font-weight: 500;
	}
	.penalties {
		font-size: 0.85em;
		color: var(--warn);
	}
	.entry-body {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0 0.75rem 0.75rem;
		overflow-x: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.95em;
	}
	th {
		text-align: left;
		font-weight: 500;
		opacity: 0.6;
	}
	th,
	td {
		padding: 0.3rem 0.4rem;
		border-bottom: 1px solid var(--line);
	}
	.num {
		font-variant-numeric: tabular-nums;
		opacity: 0.7;
		width: 3rem;
	}
	.arrow {
		opacity: 0.4;
		width: 1rem;
	}
	.changed {
		color: var(--warn);
	}
	.warn {
		margin: 0;
		color: var(--warn);
	}
	.empty {
		opacity: 0.8;
	}
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.25rem 1rem;
		margin: 0;
	}
	dt {
		opacity: 0.6;
	}
	dd {
		margin: 0;
	}
</style>
