<script lang="ts">
	import {
		formatLength,
		formatSimilarity,
		type AnswerBody,
		type Candidate,
		type ImportItem,
		type ImportTrack,
		type MatchQuestion
	} from '$lib/api';

	let { question, onanswer }: { question: MatchQuestion; onanswer: (body: AnswerBody) => void } =
		$props();

	// Whether to keep files the release doesn't have; the last choice is remembered.
	const KEEP_KEY = 'beets-webui.import.keepUnmatched';
	let keepUnmatched = $state(loadKeep());

	function loadKeep() {
		try {
			return localStorage.getItem(KEEP_KEY) === 'true';
		} catch {
			return false; // Storage can be unavailable (private windows).
		}
	}

	$effect(() => {
		try {
			localStorage.setItem(KEEP_KEY, String(keepUnmatched));
		} catch {
			// Not remembered, but still applied.
		}
	});

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
	const unmatchedCount = $derived(candidate?.extra_items?.length ?? 0);

	function apply() {
		onanswer({
			type: 'apply',
			candidate: selected,
			...(unmatchedCount && { keep_unmatched: keepUnmatched })
		});
	}
	// Abort lives in the page's status bar, so it isn't repeated here.
	const actions = $derived(question.choices.filter((c) => c.short !== 'b'));

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

	type TrackRow = { item: ImportItem | null; track: ImportTrack };
	type Row = TrackRow | { item: ImportItem; track: null };

	// The release's tracklist in order, with tracks missing from your files in their place,
	// followed by files that don't match any track.
	const rows = $derived.by((): Row[] => {
		if (!candidate?.tracks) return [];
		const tracklist: TrackRow[] = [
			...candidate.tracks,
			...(candidate.extra_tracks ?? []).map((track) => ({ item: null, track }))
		].sort((a, b) => (a.track.index ?? 0) - (b.track.index ?? 0));
		const unmatched = (candidate.extra_items ?? []).map((item) => ({ item, track: null }));
		return [...tracklist, ...unmatched];
	});

	/** Colour for a length difference; beets itself tolerates up to 10 seconds. */
	function lengthClass(a: number | null | undefined, b: number | null | undefined) {
		if (a == null || b == null) return '';
		const diff = Math.abs(a - b);
		return diff > 10 ? 'bad' : diff > 3 ? 'warn' : '';
	}

	function trackNumber(track: ImportTrack) {
		return track.medium_index ?? track.index;
	}

	/**
	 * Whether a file's track number disagrees with the release, by beets' rule: numbering per disc
	 * or across the whole release both count as matching, and files without a number are ignored.
	 */
	function numberDiffers(item: ImportItem | null, track: ImportTrack) {
		if (!item?.track || !track.index) return false;
		return item.track !== track.medium_index && item.track !== track.index;
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

	<div class="actions">
		{#if candidate}
			<button class="primary" onclick={apply}>
				Apply {formatSimilarity(candidate)}% match
			</button>
		{/if}
		{#if unmatchedCount}
			<label class="keep" title="beets imports only the files that match a track on the release">
				<input type="checkbox" bind:checked={keepUnmatched} />
				Keep {unmatchedCount === 1 ? 'the file' : `the ${unmatchedCount} files`} this release doesn't
				have
			</label>
		{/if}
		{#each actions as choice (choice.short)}
			<button onclick={() => onanswer({ type: 'choice', short: choice.short })}>
				{labels[choice.short] ?? choice.long}
			</button>
		{/each}
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

	{#if question.candidates.length === 0}
		<p class="empty">No matches found. Search by name or ID above, or choose what to do.</p>
	{:else}
		<div class="layout">
			<ol class="candidates">
				{#each question.candidates as c (c.index)}
					<li>
						<button class:selected={c.index === selected} onclick={() => (selected = c.index)}>
							<span class="score {c.strength}">{formatSimilarity(c)}%</span>
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
								<tr>
									<th>#</th>
									<th>Your file</th>
									<th class="num">Length</th>
									<th></th>
									<th>Match</th>
									<th class="num">Length</th>
								</tr>
							</thead>
							<tbody>
								{#each rows as { item, track }}
									<tr class:missing={!item} class:unmatched={!track}>
										{#if track}
											<td
												class="num"
												class:warn={numberDiffers(item, track)}
												title={numberDiffers(item, track)
													? `Your file says track ${item?.track}`
													: undefined}
											>
												{trackNumber(track)}
											</td>
										{:else}
											<td class="num">{item?.track || ''}</td>
										{/if}
										{#if item}
											<td>{item.title || item.path.split('/').pop()}</td>
											<td class="num">{formatLength(item.length)}</td>
										{:else}
											<td class="bad">missing from your files</td>
											<td class="num"></td>
										{/if}
										<td class="arrow">→</td>
										{#if track}
											<td class:warn={item && changed(item.title, track.title)}>{track.title}</td>
											<td class="num {item ? lengthClass(item.length, track.length) : ''}">
												{formatLength(track.length)}
											</td>
										{:else}
											<td class={keepUnmatched ? 'warn' : 'bad'}>
												{keepUnmatched
													? 'not on this release: kept with the album'
													: "not on this release: won't be imported"}
											</td>
											<td class="num"></td>
										{/if}
									</tr>
								{/each}
							</tbody>
						</table>
					{:else}
						<dl>
							<dt>Your file</dt>
							<dd>{task.items[0]?.title} ({formatLength(task.items[0]?.length)})</dd>
							<dt>Match</dt>
							<dd>
								<span class:warn={changed(task.items[0]?.title, candidate.name)}
									>{candidate.name}</span
								>
								(<span class={lengthClass(task.items[0]?.length, candidate.length)}
									>{formatLength(candidate.length)}</span
								>)
							</dd>
						</dl>
					{/if}
					{#if candidate.disambig}<p class="meta">{candidate.disambig}</p>{/if}
				</div>
			{/if}
		</div>
	{/if}
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
	.warn,
	.num.warn {
		color: var(--warn);
		opacity: 1;
	}
	.bad,
	.num.bad {
		color: var(--bad);
		opacity: 1;
	}
	tr.missing,
	tr.unmatched {
		background: color-mix(in srgb, var(--bad) 8%, transparent);
	}
	tr.missing .bad,
	tr.unmatched .bad {
		font-style: italic;
	}
	.empty {
		opacity: 0.8;
	}
	.primary {
		align-self: flex-start;
	}
	.keep {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		font-size: 0.9em;
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
