<script lang="ts">
	import { page } from '$app/state';
	import { api } from '$lib/api';

	const album = $derived(api.album(Number(page.params.id)));

	function duration(seconds: number) {
		const s = Math.round(seconds);
		return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	}
</script>

{#await album}
	<p>Loading…</p>
{:then album}
	<h1>{album.album}</h1>
	<p>{album.albumartist}{album.year ? ` · ${album.year}` : ''}</p>
	<table>
		<tbody>
			{#each album.items as item (item.id)}
				<tr>
					<td>{item.track}</td>
					<td>{item.title}</td>
					<td>{item.artist}</td>
					<td>{duration(item.length)}</td>
				</tr>
			{/each}
		</tbody>
	</table>
{:catch error}
	<p class="error">{error}</p>
{/await}

<style>
	table {
		width: 100%;
		border-collapse: collapse;
	}
	td {
		padding: 0.4rem 0.5rem;
		border-bottom: 1px solid color-mix(in srgb, currentColor 10%, transparent);
	}
	td:first-child,
	td:last-child {
		width: 4rem;
		opacity: 0.6;
		font-variant-numeric: tabular-nums;
	}
	.error {
		color: crimson;
	}
</style>
