<script lang="ts">
	import { api, formatLength } from '$lib/api';
	import { player } from '$lib/player.svelte';

	let audio = $state<HTMLAudioElement>();
	// While the seek bar is dragged it shows the drag, not the playing position.
	let dragging = $state<number | null>(null);

	const track = $derived(player.current);
	const albumId = $derived(typeof track?.album_id === 'number' ? track.album_id : null);
	// An album's track shows the album's cover (the small one); a single track its own.
	const cover = $derived(
		track ? (albumId != null ? api.artUrl(albumId, 0, true) : api.itemArtUrl(track.id)) : ''
	);

	$effect(() => {
		player.audio = audio ?? null;
	});

	// The audio element follows the shared state: a new track loads, play/pause applies.
	$effect(() => {
		if (!audio || !track) return;
		const src = api.itemFileUrl(track.id);
		if (!audio.src.endsWith(src)) {
			audio.src = src;
			player.time = 0;
			player.duration = Number(track.length) || 0;
		}
		if (player.playing) {
			audio.play().catch((e: DOMException) => {
				// Interrupted by the next track loading: that one plays instead.
				if (e.name === 'AbortError') return;
				// Autoplay rules can refuse until the page is interacted with; that's not a failure.
				if (e.name === 'NotAllowedError') player.playing = false;
				else failed();
			});
		} else {
			audio.pause();
		}
	});

	function failed() {
		const format = track?.format ? ` (${track.format})` : '';
		player.error = `This browser can't play this file${format}, or it's missing.`;
		player.playing = false;
	}

	// Lock screen, notification and media key controls, where the browser has them.
	$effect(() => {
		if (!('mediaSession' in navigator)) return;
		if (!track) {
			navigator.mediaSession.metadata = null;
			return;
		}
		navigator.mediaSession.metadata = new MediaMetadata({
			title: track.title || 'Untitled',
			artist: track.artist ?? '',
			album: track.album ?? '',
			artwork: [{ src: new URL(cover, location.href).href }]
		});
		const handlers: [MediaSessionAction, MediaSessionActionHandler][] = [
			['play', () => (player.playing = true)],
			['pause', () => (player.playing = false)],
			['nexttrack', () => player.next()],
			['previoustrack', () => player.previous()],
			['seekto', (d) => d.seekTime != null && player.seek(d.seekTime)]
		];
		for (const [action, handler] of handlers) {
			try {
				navigator.mediaSession.setActionHandler(action, handler);
			} catch {
				// Not every browser knows every action.
			}
		}
	});

	$effect(() => {
		if ('mediaSession' in navigator)
			navigator.mediaSession.playbackState = !track
				? 'none'
				: player.playing
					? 'playing'
					: 'paused';
	});

	function artistUrl(name: string) {
		return `/artist?${new URLSearchParams({ name })}`;
	}
</script>

<audio
	bind:this={audio}
	preload="auto"
	ontimeupdate={() => audio && (player.time = audio.currentTime)}
	ondurationchange={() => audio && isFinite(audio.duration) && (player.duration = audio.duration)}
	onended={() => player.next()}
	onerror={() => track && failed()}
	onpause={() => audio && !audio.ended && (player.playing = false)}
	onplay={() => (player.playing = true)}
></audio>

{#if track}
	<div class="bar" role="region" aria-label="Player">
		<div class="seek">
			<span class="time">{formatLength(dragging ?? player.time)}</span>
			<input
				type="range"
				min="0"
				max={player.duration || 0}
				step="1"
				value={dragging ?? player.time}
				aria-label="Position"
				oninput={(e) => (dragging = Number(e.currentTarget.value))}
				onchange={(e) => {
					player.seek(Number(e.currentTarget.value));
					dragging = null;
				}}
			/>
			<span class="time">{formatLength(player.duration)}</span>
		</div>
		<div class="row">
			<div class="cover">
				{#key cover}<img src={cover} alt="" onerror={(e) => e.currentTarget.remove()} />{/key}
			</div>
			<div class="info">
				<a class="title" href="/songs/{track.id}">{track.title || 'Untitled'}</a>
				<span class="meta">
					{#if track.artist}<a href={artistUrl(track.artist)}>{track.artist}</a>{/if}
					{#if track.album}
						·
						{#if albumId != null}<a href="/albums/{albumId}">{track.album}</a
							>{:else}{track.album}{/if}
					{/if}
				</span>
				{#if player.error}<span class="error">{player.error}</span>{/if}
			</div>
			<div class="controls">
				<button
					type="button"
					aria-label="Previous"
					title="Previous"
					onclick={() => player.previous()}>⏮</button
				>
				<button
					type="button"
					class="main"
					aria-label={player.playing ? 'Pause' : 'Play'}
					title={player.playing ? 'Pause' : 'Play'}
					onclick={() => player.toggle()}>{player.playing ? '❚❚' : '▶'}</button
				>
				<button
					type="button"
					aria-label="Next"
					title="Next"
					disabled={player.index >= player.queue.length - 1}
					onclick={() => player.next()}>⏭</button
				>
			</div>
			<span class="position meta">{player.index + 1} / {player.queue.length}</span>
			<button
				type="button"
				class="close"
				aria-label="Stop and close the player"
				title="Stop and close"
				onclick={() => player.close()}>✕</button
			>
		</div>
	</div>
{/if}

<style>
	.bar {
		position: fixed;
		left: 0;
		right: 0;
		bottom: 0;
		z-index: 10;
		background: Canvas;
		border-top: 1px solid var(--line);
		padding: 0.4rem 1rem calc(0.5rem + env(safe-area-inset-bottom));
		box-shadow: 0 -2px 12px color-mix(in srgb, CanvasText 8%, transparent);
	}
	.seek {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		max-width: 1200px;
		margin: 0 auto;
	}
	.seek input {
		flex: 1;
		min-width: 0;
		padding: 0;
		border: none;
		accent-color: var(--accent);
	}
	.time {
		font-size: 0.8em;
		opacity: 0.6;
		font-variant-numeric: tabular-nums;
		min-width: 2.6rem;
		text-align: center;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		max-width: 1200px;
		margin: 0.25rem auto 0;
	}
	.cover {
		width: 44px;
		height: 44px;
		flex: none;
		border-radius: 4px;
		overflow: hidden;
		background: color-mix(in srgb, currentColor 10%, transparent);
	}
	.cover img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.info {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
	}
	.info > * {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.title {
		font-weight: 500;
	}
	a {
		color: inherit;
		text-decoration: none;
	}
	a:hover {
		text-decoration: underline;
	}
	.meta {
		font-size: 0.85em;
		opacity: 0.7;
	}
	.error {
		font-size: 0.8em;
		color: var(--bad);
	}
	.controls {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		flex: none;
	}
	.controls button,
	.close {
		background: none;
		border: none;
		padding: 0.35rem 0.5rem;
		line-height: 1;
	}
	.controls .main {
		width: 2.4rem;
		height: 2.4rem;
		border-radius: 50%;
		background: var(--accent);
		color: white;
	}
	.close {
		opacity: 0.6;
	}
	@media (max-width: 640px) {
		.position {
			display: none;
		}
	}
</style>
