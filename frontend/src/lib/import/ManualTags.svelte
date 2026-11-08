<script lang="ts">
	import { fieldText as text, type AnswerBody, type ImportItem, type ImportTask } from '$lib/api';

	let {
		task,
		onanswer,
		oncancel
	}: { task: ImportTask; onanswer: (body: AnswerBody) => void; oncancel: () => void } = $props();

	const albumFields = [
		{ key: 'album', label: 'Album' },
		{ key: 'albumartist', label: 'Album artist' },
		{ key: 'year', label: 'Year', numeric: true },
		{ key: 'genres', label: 'Genres', hint: 'Separate with ;' },
		{ key: 'label', label: 'Label' },
		{ key: 'catalognum', label: 'Catalog number' },
		{ key: 'country', label: 'Country', hint: 'e.g. GB' }
	];
	const moreFields = [
		{ key: 'month', label: 'Month', numeric: true },
		{ key: 'day', label: 'Day', numeric: true },
		{ key: 'original_year', label: 'Original year', numeric: true },
		{ key: 'albumtypes', label: 'Album types', hint: 'Separate with ; (album, ep, live…)' },
		{ key: 'albumstatus', label: 'Status', hint: 'official, promotion, bootleg…' },
		{ key: 'albumdisambig', label: 'Disambiguation', hint: 'e.g. deluxe edition' },
		{ key: 'media', label: 'Media', hint: 'CD, Digital Media, Vinyl…' },
		{ key: 'barcode', label: 'Barcode' },
		{ key: 'language', label: 'Language', hint: 'e.g. eng' },
		{ key: 'script', label: 'Script', hint: 'e.g. Latn' }
	];
	const itemFields = ['disc', 'track', 'title', 'artist'] as const;

	const isAlbum = $derived(task.kind === 'album');

	// Files in the order of their tags (disc, then track), then by name.
	const files = $derived(
		[...task.items].sort(
			(a, b) =>
				(a.disc || 0) - (b.disc || 0) ||
				(a.track || 0) - (b.track || 0) ||
				a.path.localeCompare(b.path)
		)
	);

	// Starts from the files' own tags. The form isn't rebuilt when the page gets a fresh copy of
	// the same question (it does whenever the import logs something), which would undo changes.
	// svelte-ignore state_referenced_locally
	const startAlbum = Object.fromEntries(
		[...albumFields, ...moreFields].map((f) => [f.key, text(task.album_tags[f.key])])
	);
	// svelte-ignore state_referenced_locally
	const startItems = Object.fromEntries(
		task.items.map((item) => [
			item.path,
			Object.fromEntries(itemFields.map((f) => [f, text(item[f])]))
		])
	);
	// svelte-ignore state_referenced_locally
	const startComp = Boolean(task.album_tags.comp);
	let albumForm = $state<Record<string, string>>({ ...startAlbum });
	let itemForms = $state<Record<string, Record<string, string>>>(structuredClone(startItems));
	let comp = $state(startComp);

	function fileName(item: ImportItem) {
		return item.path.split('/').pop() ?? item.path;
	}

	/** Number the files 1, 2, 3… in the order shown, restarting on each disc. */
	function numberInOrder() {
		const counts: Record<string, number> = {};
		for (const f of files) {
			const disc = itemForms[f.path].disc;
			counts[disc] = (counts[disc] ?? 0) + 1;
			itemForms[f.path].track = String(counts[disc]);
		}
	}

	/** Disc and track numbers that more than one file has. */
	const clashes = $derived.by(() => {
		const seen = new Map<string, number>();
		for (const f of files) {
			const { disc, track } = itemForms[f.path];
			if (!track) continue;
			const key = `${disc || 1}:${track}`;
			seen.set(key, (seen.get(key) ?? 0) + 1);
		}
		return new Set([...seen].filter(([, n]) => n > 1).map(([key]) => key));
	});

	function numberClashes(item: ImportItem) {
		const { disc, track } = itemForms[item.path];
		return Boolean(track) && clashes.has(`${disc || 1}:${track}`);
	}

	function submit() {
		// Only what changed, so the files keep tags as they were where nothing was entered.
		const album: Record<string, string> = {};
		for (const [key, value] of Object.entries(albumForm)) {
			if (value !== startAlbum[key]) album[key] = value;
		}
		if (comp !== startComp) album.comp = String(comp);
		const items: Record<string, Record<string, string>> = {};
		for (const [path, fields] of Object.entries(itemForms)) {
			const changed = Object.fromEntries(
				Object.entries(fields).filter(([key, value]) => value !== startItems[path][key])
			);
			if (Object.keys(changed).length) items[path] = changed;
		}
		onanswer({ type: 'manual', album, items });
	}
</script>

<form
	class="manual"
	onsubmit={(e) => {
		e.preventDefault();
		submit();
	}}
>
	<p class="meta">
		Import {isAlbum ? 'these files' : 'this file'} with the tags below instead of a release's. They're
		written to the files; release IDs the files carry are removed, so nothing re-applies that release
		over them.
	</p>

	<div class="fields">
		{#each albumFields as f (f.key)}
			<label>
				<span>{f.label}</span>
				<input
					bind:value={albumForm[f.key]}
					placeholder={f.hint}
					inputmode={f.numeric ? 'numeric' : undefined}
				/>
			</label>
		{/each}
	</div>

	<details>
		<summary>More fields</summary>
		<div class="fields">
			{#each moreFields as f (f.key)}
				<label>
					<span>{f.label}</span>
					<input
						bind:value={albumForm[f.key]}
						placeholder={f.hint}
						inputmode={f.numeric ? 'numeric' : undefined}
					/>
				</label>
			{/each}
			<label class="check">
				<input type="checkbox" bind:checked={comp} />
				<span>Compilation (various artists)</span>
			</label>
		</div>
	</details>

	<table>
		<thead>
			<tr>
				<th class="num">Disc</th>
				<th class="num">#</th>
				<th>Title</th>
				<th>Artist</th>
				<th class="file">File</th>
			</tr>
		</thead>
		<tbody>
			{#each files as item (item.path)}
				<tr>
					<td class="num"
						><input
							bind:value={itemForms[item.path].disc}
							inputmode="numeric"
							aria-label="Disc"
						/></td
					>
					<td class="num" class:warn={numberClashes(item)}
						><input
							bind:value={itemForms[item.path].track}
							inputmode="numeric"
							aria-label="Track number"
							title={numberClashes(item)
								? 'Another file has this disc and track number'
								: undefined}
						/></td
					>
					<td
						><input
							bind:value={itemForms[item.path].title}
							placeholder={fileName(item)}
							aria-label="Title"
						/></td
					>
					<td
						><input
							bind:value={itemForms[item.path].artist}
							placeholder={albumForm.albumartist}
							aria-label="Artist"
						/></td
					>
					<td class="file" title={item.path}>{fileName(item)}</td>
				</tr>
			{/each}
		</tbody>
	</table>
	{#if files.length > 1}
		<p class="meta">
			<button type="button" class="link" onclick={numberInOrder}>Number tracks in this order</button
			>
		</p>
	{/if}

	<div class="buttons">
		<button type="button" onclick={oncancel}>Back to matches</button>
		<button class="primary">Import with these tags</button>
	</div>
</form>

<style>
	.manual {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.meta {
		margin: 0;
		opacity: 0.65;
		font-size: 0.9em;
	}
	.fields {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
		gap: 0.75rem;
	}
	details .fields {
		margin-top: 0.75rem;
	}
	summary {
		cursor: pointer;
		font-size: 0.9em;
		opacity: 0.8;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
	}
	label span {
		font-size: 0.85em;
		opacity: 0.7;
	}
	label.check {
		flex-direction: row;
		align-items: center;
		gap: 0.4rem;
		align-self: end;
	}
	label.check span {
		font-size: 0.9em;
		opacity: 1;
	}
	input:not([type='checkbox']) {
		font: inherit;
		padding: 0.35rem 0.5rem;
		min-width: 0;
		width: 100%;
		box-sizing: border-box;
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
	td input:not([type='checkbox']) {
		padding: 0.2rem 0.35rem;
	}
	.num {
		width: 3.5rem;
		font-variant-numeric: tabular-nums;
	}
	.num.warn input {
		border-color: var(--warn);
		color: var(--warn);
	}
	.file {
		font-size: 0.85em;
		opacity: 0.6;
		max-width: 12rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	@media (max-width: 760px) {
		.file {
			display: none;
		}
	}
	button.link {
		background: none;
		border: none;
		padding: 0;
		color: var(--accent);
		font-size: inherit;
	}
	.buttons {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
</style>
