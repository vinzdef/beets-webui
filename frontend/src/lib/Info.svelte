<script lang="ts">
	// An ⓘ that explains something on hover, focus or tap. The tip is a popover, so it shows in
	// the top layer and isn't clipped by a scrolling container around the icon.
	let { text }: { text: string } = $props();

	let button = $state<HTMLButtonElement>();
	let tip = $state<HTMLDivElement>();

	function show() {
		if (!button || !tip) return;
		tip.showPopover();
		const r = button.getBoundingClientRect();
		const width = Math.min(280, window.innerWidth - 16);
		tip.style.width = `${width}px`;
		tip.style.left = `${Math.min(Math.max(8, r.left + r.width / 2 - width / 2), window.innerWidth - width - 8)}px`;
		tip.style.top = `${r.bottom + 6}px`;
	}

	function hide() {
		if (tip?.matches(':popover-open')) tip.hidePopover();
	}
</script>

<button
	type="button"
	class="info"
	aria-label="More information"
	bind:this={button}
	onmouseenter={show}
	onmouseleave={hide}
	onfocus={show}
	onblur={hide}
	onclick={(e) => {
		// Inside a label, a click would also toggle its checkbox.
		e.preventDefault();
		e.stopPropagation();
		if (tip?.matches(':popover-open')) hide();
		else show();
	}}>ⓘ</button
>
<div popover="manual" role="tooltip" class="tip" bind:this={tip}>{text}</div>

<style>
	.info {
		border: none;
		background: none;
		padding: 0 0.15rem;
		font-size: 0.95em;
		line-height: 1;
		opacity: 0.6;
		cursor: help;
	}
	.info:hover,
	.info:focus-visible {
		opacity: 1;
	}
	.tip {
		position: fixed;
		inset: auto;
		margin: 0;
		padding: 0.5rem 0.65rem;
		border: 1px solid var(--line);
		border-radius: 6px;
		background: Canvas;
		color: CanvasText;
		box-shadow: 0 4px 16px rgb(0 0 0 / 0.18);
		font-size: 0.85rem;
		line-height: 1.35;
		white-space: normal;
		text-align: left;
	}
</style>
