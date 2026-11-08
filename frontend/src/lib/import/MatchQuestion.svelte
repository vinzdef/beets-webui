<script lang="ts">
	import { formatLength, type AnswerBody, type Candidate, type MatchQuestion } from '$lib/api';

	let { question, onanswer }: { question: MatchQuestion; onanswer: (body: AnswerBody) => void } =
		$props();

	let selected = $state(0);
	let searchArtist = $state('');
	let searchName = $state('');
	let searchIds = $state('');

	// A new question (e.g. after a search) starts from its best candidate again.
	$effect(() => {
		question.id;
		selected = 0;
	});

	const task = $derived(question.task);
	const candidate = $derived<Candidate | undefined>(question.candidates[selected]);
	const isAlbum = $derived(task.kind === 'album');
	const actions = $derived(question.choices.filter((c) => c.short !== 'b'));
	const canAbort = $derived(question.choices.some((c) => c.short === 'b'));

	const labels: Record<string, string> = {
		s: 'Skip',
		u: 'Use as-is',
		t: 'Import as tracks',
		g: 'Group albums',
		r: 'Rescan folder'
	};

	function meta(c: Candidate): string {
		return [c.year, c.label, c.country, c.media, c.albumtype, c.data_source]
			.filter((v) => v)
			.join(' · ');
	}

	function changed(a: string | null | undefined, b: string | null | undefined) {
		return (a ?? '').trim().toLowerCase() !== (b ?? '').trim().toLowerCase();
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

	{#if question.candidates.length === 0}
		<p class="empty">No matches found. Search by name or ID below, or choose what to do.</p>
	{:else}
		<div class="layout">
			<ol class="candidates">
				{#each question.candidates as c (c.index)}
					<li>
						<button class:selected={c.index === selected} onclick={() => (selected = c.index)}>
							<span class="score {c.strength}">{c.similarity.toFixed(1)}%</span>
							<span class="title">{c.artist} – {c.name}</span>
							{#if meta(c)}<span class="meta">{meta(c)}</span>{/if}
							{#if !isAlbum && c.album}<span class="meta">{c.album}</span>{/if}
							{#if c.penalties.length}
								<span class="penalties">≠ {c.penalties.join(', ')}</span>
							{/if}
						</button>
					</li>
				{/each}
			</ol>

			{#if candidate}
				<div class="detail">
					{#if isAlbum && candidate.tracks}
						<table>
							<thead>
								<tr><th>#</th><th>Your file</th><th></th><th>Match</th><th>Length</th></tr>
							</thead>
							<tbody>
								{#each candidate.tracks as { item, track }}
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
						{#if candidate.extra_tracks?.length}
							<p class="warn">
								Missing tracks: {candidate.extra_tracks.map((t) => t.title).join(', ')}
							</p>
						{/if}
						{#if candidate.extra_items?.length}
							<p class="warn">
								Unmatched files: {candidate.extra_items.map((i) => i.title || i.path).join(', ')}
							</p>
						{/if}
					{:else}
						<dl>
							<dt>Your file</dt>
							<dd>{task.items[0]?.title} ({formatLength(task.items[0]?.length)})</dd>
							<dt>Match</dt>
							<dd>{candidate.name} ({formatLength(candidate.length)})</dd>
						</dl>
					{/if}
					{#if candidate.disambig}<p class="meta">{candidate.disambig}</p>{/if}
					<button class="primary" onclick={() => onanswer({ type: 'apply', candidate: selected })}>
						Apply {candidate.similarity.toFixed(0)}% match
					</button>
				</div>
			{/if}
		</div>
	{/if}

	<div class="actions">
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

	<div class="searches">
		<form
			onsubmit={(e) => {
				e.preventDefault();
				onanswer({ type: 'search', artist: searchArtist, name: searchName });
			}}
		>
			<input bind:value={searchArtist} placeholder="Artist" />
			<input bind:value={searchName} placeholder={isAlbum ? 'Album' : 'Title'} />
			<button>Search</button>
		</form>
		<form
			onsubmit={(e) => {
				e.preventDefault();
				onanswer({ type: 'id', ids: searchIds });
			}}
		>
			<input bind:value={searchIds} placeholder="MusicBrainz ID or URL" />
			<button>Look up</button>
		</form>
	</div>
</section>

<style>
	.question {
		display: flex;
		flex-direction: column;
		gap: 1rem;
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
	.layout {
		display: grid;
		grid-template-columns: minmax(240px, 1fr) 2fr;
		gap: 1rem;
	}
	@media (max-width: 760px) {
		.layout {
			grid-template-columns: 1fr;
		}
	}
	.candidates {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.candidates button {
		width: 100%;
		text-align: left;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		padding: 0.6rem 0.75rem;
	}
	.candidates button.selected {
		outline: 2px solid var(--accent);
	}
	.score {
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
		font-weight: 500;
	}
	.penalties {
		font-size: 0.85em;
		color: var(--warn);
	}
	.detail {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		min-width: 0;
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
	.primary {
		align-self: flex-start;
	}
	.actions,
	.searches {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.searches form {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.danger {
		margin-left: auto;
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
