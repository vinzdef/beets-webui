<script lang="ts">
	import Info from '$lib/Info.svelte';
	import type { ImportMode } from '$lib/api';

	// A dropdown rather than a <select>: each mode carries an ⓘ, and the menu is a popover so the
	// scrolling toolbar it sits in doesn't clip it.
	let { value = $bindable() }: { value: ImportMode } = $props();

	const modes: { value: ImportMode; label: string; help: string }[] = [
		{
			value: 'auto',
			label: 'Auto',
			help: 'Matches above the strong-match threshold in your beets config are applied without asking; you choose the rest.'
		},
		{
			value: 'manual',
			label: 'Manual',
			help: 'Only perfect (100%) matches are applied without asking; you approve every other one.'
		},
		{
			value: 'timid',
			label: 'Timid',
			help: 'You approve every match, even perfect ones.'
		}
	];

	let button = $state<HTMLButtonElement>();
	let menu = $state<HTMLDivElement>();
	const current = $derived(modes.find((m) => m.value === value) ?? modes[1]);

	function toggle() {
		if (!button || !menu) return;
		if (menu.matches(':popover-open')) {
			menu.hidePopover();
			return;
		}
		menu.showPopover();
		const r = button.getBoundingClientRect();
		menu.style.left = `${Math.min(r.left, window.innerWidth - menu.offsetWidth - 8)}px`;
		menu.style.top = `${r.bottom + 4}px`;
		menu.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
	}

	function choose(mode: ImportMode) {
		value = mode;
		menu?.hidePopover();
		button?.focus();
	}
</script>

<span class="mode">
	<span class="label">Mode</span>
	<button
		type="button"
		bind:this={button}
		aria-haspopup="menu"
		onclick={toggle}
		onkeydown={(e) => {
			if (e.key === 'ArrowDown') {
				e.preventDefault();
				toggle();
			}
		}}>{current.label} ▾</button
	>
</span>
<div popover="auto" role="menu" class="menu" bind:this={menu}>
	{#each modes as mode, i (mode.value)}
		<div class="item">
			<button
				type="button"
				role="menuitemradio"
				aria-checked={mode.value === value}
				onclick={() => choose(mode.value)}
				onkeydown={(e) => {
					const items = menu?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]');
					if (!items) return;
					if (e.key === 'ArrowDown') items[(i + 1) % items.length].focus();
					else if (e.key === 'ArrowUp') items[(i - 1 + items.length) % items.length].focus();
					else return;
					e.preventDefault();
				}}
			>
				<span class="check">{mode.value === value ? '✓' : ''}</span>{mode.label}
			</button>
			<Info text={mode.help} />
		</div>
	{/each}
</div>

<style>
	.mode {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
	}
	.label {
		opacity: 0.7;
	}
	.menu {
		position: fixed;
		inset: auto;
		margin: 0;
		padding: 0.3rem;
		min-width: 10rem;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: Canvas;
		color: CanvasText;
		box-shadow: 0 6px 20px rgb(0 0 0 / 0.2);
	}
	.item {
		display: flex;
		align-items: center;
	}
	.item button[role='menuitemradio'] {
		flex: 1;
		text-align: left;
		border: none;
		background: none;
		padding: 0.35rem 0.5rem;
		border-radius: 5px;
	}
	.item button[role='menuitemradio']:hover,
	.item button[role='menuitemradio']:focus-visible {
		background: var(--subtle);
	}
	.check {
		display: inline-block;
		width: 1.1rem;
		color: var(--accent);
	}
</style>
