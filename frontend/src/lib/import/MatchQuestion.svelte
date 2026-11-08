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

	// A new question (e.g. after a search) starts from its best candidate again. The page gets a
	// fresh copy of the same question whenever the import logs something, so compare ids.
	let selectedFor = -1;
	$effect(() => {
		if (question.id === selectedFor) return;
		selectedFor = question.id;
		selected = 0;
	});

	const task = $derived(question.task);
	const candidate = $derived<Candidate | undefined>(question.candidates[selected]);
	const isAlbum = $derived(task.kind === 'album');

	// Your files and the release's tracks, for pairing them by hand.
	const files = $derived<ImportItem[]>(
		candidate?.tracks
			? [...candidate.tracks.map((t) => t.item), ...(candidate.extra_items ?? [])]
			: []
	);
	const releaseTracks = $derived<ImportTrack[]>(
		candidate?.tracks
			? [...candidate.tracks.map((t) => t.track), ...(candidate.extra_tracks ?? [])].sort(
					(a, b) => a.pos - b.pos
				)
			: []
	);
	// How beets paired them: file path -> the track's position on the release, or null.
	const ownPairing = $derived<Record<string, number | null>>(
		candidate?.tracks
			? Object.fromEntries([
					...candidate.tracks.map((t) => [t.item.path, t.track.pos]),
					...(candidate.extra_items ?? []).map((i) => [i.path, null])
				])
			: {}
	);
	let pairing = $state<Record<string, number | null>>({});
	// Title and track number for files the release doesn't have, as chosen; an empty track
	// means the default, after the release's last track.
	let extraTags = $state<Record<string, { title: string; track: string }>>({});

	// Each candidate starts from beets' own pairing and the files' own tags; fresh copies of the
	// same question (see above) keep what you've changed.
	let pairedFor = '';
	$effect(() => {
		const key = `${question.id}:${selected}`;
		if (key === pairedFor) return;
		pairedFor = key;
		pairing = { ...ownPairing };
		extraTags = Object.fromEntries(files.map((f) => [f.path, { title: f.title ?? '', track: '' }]));
	});

	const pairedByHand = $derived(
		Object.keys(ownPairing).some((path) => pairing[path] !== ownPairing[path])
	);
	const unpaired = $derived(files.filter((f) => pairing[f.path] === null));
	const unmatchedCount = $derived(unpaired.length);
	const nothingPaired = $derived(
		files.length > 0 && files.every((f) => (pairing[f.path] ?? null) === null)
	);

	/** Pair a file with a track; a file that had that track takes this file's old one. */
	function pair(path: string, pos: number | null) {
		const next = { ...pairing };
		if (pos !== null) {
			const other = Object.keys(next).find((p) => p !== path && next[p] === pos);
			if (other) next[other] = next[path];
		}
		next[path] = pos;
		pairing = next;
	}

	// The release's highest track number: kept files go after it unless you pick otherwise.
	const lastTrack = $derived(Math.max(0, ...releaseTracks.map((t) => trackNumber(t) ?? 0)));
	// Numbers to choose from: the release's, then one more for each kept file.
	const trackChoices = $derived(
		Array.from({ length: lastTrack + unpaired.length }, (_, i) => i + 1)
	);
	const takenBy = $derived(
		new Map(releaseTracks.map((t) => [trackNumber(t), t.title ?? `track ${trackNumber(t)}`]))
	);

	/** The track number a kept file ends up with: as chosen, or next after the release's tracks. */
	function keptNumber(file: ImportItem): number {
		const chosen = extraTags[file.path]?.track;
		return chosen ? Number(chosen) : lastTrack + unpaired.indexOf(file) + 1;
	}

	/** Whether another kept file, or a track on the release, ends up with the same number. */
	function numberClashes(file: ImportItem): boolean {
		const n = keptNumber(file);
		return takenBy.has(n) || unpaired.some((f) => f !== file && keptNumber(f) === n);
	}

	function apply() {
		// Kept files get the number shown, and a title only when it was changed.
		const tags: Record<string, { title: string | null; track: number | null }> = {};
		for (const f of unpaired) {
			const title = extraTags[f.path].title;
			tags[f.path] = {
				title: title !== (f.title ?? '') ? title || null : null,
				track: keptNumber(f)
			};
		}
		onanswer({
			type: 'apply',
			candidate: selected,
			...(pairedByHand && { mapping: pairing }),
			...(unmatchedCount && { keep_unmatched: keepUnmatched }),
			...(keepUnmatched && Object.keys(tags).length && { extra_tags: tags })
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

	// The release's tracklist in order, each track with the file paired with it (or missing),
	// followed by files that aren't on the release.
	const rows = $derived.by((): Row[] => {
		const byPos = new Map(
			files.filter((f) => pairing[f.path] != null).map((f) => [pairing[f.path], f])
		);
		const tracklist: TrackRow[] = releaseTracks.map((track) => ({
			item: byPos.get(track.pos) ?? null,
			track
		}));
		return [...tracklist, ...unpaired.map((item) => ({ item, track: null }))];
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
			<button
				class="primary"
				disabled={nothingPaired}
				title={nothingPaired ? 'Pair at least one file with a track, or use as-is' : undefined}
				onclick={apply}
			>
				Apply {formatSimilarity(candidate)}% match{pairedByHand ? ', paired by hand' : ''}
			</button>
		{/if}
		{#each actions as choice (choice.short)}
			<button onclick={() => onanswer({ type: 'choice', short: choice.short })}>
				{labels[choice.short] ?? choice.long}
			</button>
		{/each}
	</div>

	{#if unmatchedCount}
		<label class="keep" title="beets imports only the files that match a track on the release">
			<input type="checkbox" bind:checked={keepUnmatched} />
			Keep {unmatchedCount === 1 ? 'the file' : `the ${unmatchedCount} files`} this release doesn't have
		</label>
	{/if}

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
										{:else if item && keepUnmatched}
											<td class="num" class:warn={numberClashes(item)}>
												<select
													class="number"
													value={String(keptNumber(item))}
													aria-label="Track number after import"
													title={numberClashes(item)
														? 'Another track ends up with this number too'
														: 'The track number this file gets'}
													onchange={(e) => (extraTags[item.path].track = e.currentTarget.value)}
												>
													{#each trackChoices as n (n)}
														<option value={String(n)}
															>{n}{takenBy.has(n)
																? ` · same as ${takenBy.get(n)}`
																: n === item.track
																	? ' (in its tags)'
																	: ''}</option
														>
													{/each}
												</select>
											</td>
										{:else}
											<td class="num">{item?.track || ''}</td>
										{/if}
										{#if item && !track && keepUnmatched}
											<td>
												<input
													class="tag"
													bind:value={extraTags[item.path].title}
													placeholder={item.path.split('/').pop()}
													aria-label="Title"
												/>
											</td>
											<td class="num">{formatLength(item.length)}</td>
										{:else if item}
											<td title={item.path.split('/').pop()}>
												{item.title || item.path.split('/').pop()}
											</td>
											<td class="num">{formatLength(item.length)}</td>
										{:else}
											<td class="bad">missing from your files</td>
											<td class="num"></td>
										{/if}
										<td class="arrow">→</td>
										{#if item}
											<td class:warn={track && changed(item.title, track.title)}>
												<select
													value={track?.pos ?? -1}
													aria-label="Release track for {item.title || item.path}"
													onchange={(e) => {
														const pos = Number(e.currentTarget.value);
														pair(item.path, pos < 0 ? null : pos);
													}}
												>
													{#each releaseTracks as t (t.pos)}
														<option value={t.pos}>{trackNumber(t)}. {t.title}</option>
													{/each}
													<option value={-1}>Not on this release</option>
												</select>
												{#if !track}
													<small class={keepUnmatched ? 'warn' : 'bad'}>
														{keepUnmatched ? 'kept with the album' : "won't be imported"}
													</small>
												{/if}
											</td>
										{:else}
											<td>{track?.title}</td>
										{/if}
										{#if track}
											<td class="num {item ? lengthClass(item.length, track.length) : ''}">
												{formatLength(track.length)}
											</td>
										{:else}
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
					{#if pairedByHand}
						<p class="meta">
							Paired by hand; the match percentage is for beets' own pairing.
							<button class="link" onclick={() => (pairing = { ...ownPairing })}
								>Reset pairing</button
							>
						</p>
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
	td select {
		width: 100%;
		max-width: 22rem;
		font: inherit;
		font-size: 0.95em;
		padding: 0.15rem 0.2rem;
		color: inherit;
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 4px;
	}
	td small {
		display: block;
		font-size: 0.8em;
	}
	/* The closed dropdown shows just the number; the open list explains each one. */
	select.number {
		width: 3.6rem;
	}
	input.tag {
		font: inherit;
		width: 100%;
		min-width: 2.5rem;
		box-sizing: border-box;
		padding: 0.1rem 0.3rem;
	}
	button.link {
		background: none;
		border: none;
		padding: 0;
		color: var(--accent);
		font-size: inherit;
	}
	/* Just below the buttons, closer than the question's usual spacing. */
	.keep {
		display: inline-flex;
		align-self: flex-start;
		align-items: center;
		gap: 0.35rem;
		font-size: 0.9em;
		margin-top: -0.5rem;
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
