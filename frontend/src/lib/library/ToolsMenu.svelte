<script lang="ts">
	// A button that opens a menu of library-wide actions; the menu is a popover, so it shows
	// above everything else.
	let { items }: { items: { label: string; action: () => void }[] } = $props();

	let button = $state<HTMLButtonElement>();
	let menu = $state<HTMLDivElement>();

	function toggle() {
		if (!button || !menu) return;
		if (menu.matches(':popover-open')) {
			menu.hidePopover();
			return;
		}
		menu.showPopover();
		const r = button.getBoundingClientRect();
		menu.style.left = `${Math.max(8, Math.min(r.right - menu.offsetWidth, window.innerWidth - menu.offsetWidth - 8))}px`;
		menu.style.top = `${r.bottom + 4}px`;
		menu.querySelector<HTMLButtonElement>('button')?.focus();
	}

	function run(action: () => void) {
		menu?.hidePopover();
		action();
	}
</script>

<button type="button" bind:this={button} aria-haspopup="menu" onclick={toggle}
	>Library tools ▾</button
>
<div popover="auto" role="menu" class="menu" bind:this={menu}>
	{#each items as item, i (item.label)}
		<button
			type="button"
			role="menuitem"
			onclick={() => run(item.action)}
			onkeydown={(e) => {
				const buttons = menu?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]');
				if (!buttons) return;
				if (e.key === 'ArrowDown') buttons[(i + 1) % buttons.length].focus();
				else if (e.key === 'ArrowUp') buttons[(i - 1 + buttons.length) % buttons.length].focus();
				else return;
				e.preventDefault();
			}}>{item.label}</button
		>
	{/each}
</div>

<style>
	.menu {
		position: fixed;
		inset: auto;
		margin: 0;
		padding: 0.3rem;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: Canvas;
		color: CanvasText;
		box-shadow: 0 6px 20px rgb(0 0 0 / 0.2);
	}
	.menu button {
		display: block;
		width: 100%;
		text-align: left;
		border: none;
		background: none;
		padding: 0.4rem 0.6rem;
		border-radius: 5px;
		white-space: nowrap;
	}
	.menu button:hover,
	.menu button:focus-visible {
		background: var(--subtle);
	}
</style>
