import type { Item } from '$lib/api';

/**
 * What's playing, shared by every page: a queue of tracks and where in it we are. The player
 * bar in the layout owns the <audio> element and follows this state; pages only start playback.
 */
class Player {
	queue = $state<Item[]>([]);
	index = $state(-1);
	playing = $state(false);
	/** Seconds into the current track, and its length, as the audio element reports them. */
	time = $state(0);
	duration = $state(0);
	error = $state<string | null>(null);
	current = $derived<Item | null>(this.queue[this.index] ?? null);
	/** Set by the player bar, so seeking reaches the audio element. */
	audio: HTMLAudioElement | null = null;

	/** Play `tracks` in order, starting with the one at `start`. */
	play(tracks: Item[], start = 0) {
		this.queue = tracks;
		this.index = start;
		this.error = null;
		this.playing = true;
	}

	/** Pause or resume a track that's already current; else start `tracks` from `start`. */
	playOrToggle(id: number, tracks: Item[], start: number) {
		if (this.current?.id === id) this.toggle();
		else this.play(tracks, start);
	}

	toggle() {
		if (this.current) this.playing = !this.playing;
	}

	next() {
		if (this.index < this.queue.length - 1) {
			this.index++;
			this.error = null;
			this.playing = true;
		} else {
			this.playing = false;
		}
	}

	/** Back to the start of the track, or to the one before if it only just started. */
	previous() {
		if (this.time > 3 || this.index <= 0) this.seek(0);
		else {
			this.index--;
			this.error = null;
			this.playing = true;
		}
	}

	seek(seconds: number) {
		if (this.audio) this.audio.currentTime = seconds;
	}

	close() {
		this.playing = false;
		this.queue = [];
		this.index = -1;
		this.error = null;
	}
}

export const player = new Player();
