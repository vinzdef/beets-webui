<script lang="ts">
	import type { Item } from '$lib/api';
	import { player } from '$lib/player.svelte';

	/** Plays `tracks` from `start` (the track this button is for), or pauses it when it's playing. */
	let { tracks, start }: { tracks: Item[]; start: number } = $props();

	const track = $derived(tracks[start]);
	const isCurrent = $derived(player.current?.id === track?.id);
	const label = $derived(
		isCurrent && player.playing ? 'Pause' : `Play ${track?.title || 'this track'}`
	);
</script>

<button
	type="button"
	class="play"
	class:current={isCurrent}
	aria-label={label}
	title={label}
	onclick={(e) => {
		e.preventDefault();
		e.stopPropagation();
		player.playOrToggle(track.id, tracks, start);
	}}>{isCurrent && player.playing ? '❚❚' : '▶'}</button
>

<style>
	.play {
		background: none;
		border: none;
		padding: 0 0.25rem;
		font-size: 0.8em;
		line-height: 1;
		opacity: 0.55;
		width: 1.6rem;
	}
	.play:hover,
	.play.current {
		opacity: 1;
		color: var(--accent);
	}
</style>
