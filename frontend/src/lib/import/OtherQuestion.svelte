<script lang="ts">
	import type { AnswerBody, DuplicateQuestion, ResumeQuestion } from '$lib/api';

	let {
		question,
		onanswer
	}: { question: DuplicateQuestion | ResumeQuestion; onanswer: (body: AnswerBody) => void } =
		$props();
</script>

<section class="question">
	{#if question.kind === 'duplicate'}
		<p class="eyebrow">Already in your library</p>
		<h2>{question.task.artist} – {question.task.name}</h2>
		<dl>
			{#each question.existing as existing}
				<dt>Existing</dt>
				<dd>{existing.description}<br /><span class="meta">{existing.summary}</span></dd>
			{/each}
			<dt>New</dt>
			<dd><span class="meta">{question.new}</span></dd>
		</dl>
		<div class="actions">
			{#each question.options as option (option.value)}
				<button onclick={() => onanswer({ type: 'duplicate', action: option.value })}>
					{option.label}
				</button>
			{/each}
		</div>
	{:else}
		<p class="eyebrow">Interrupted import</p>
		<h2>Resume importing this folder?</h2>
		<p class="meta">{question.path}</p>
		<div class="actions">
			<button onclick={() => onanswer({ type: 'resume', resume: true })}>Resume</button>
			<button onclick={() => onanswer({ type: 'resume', resume: false })}>Start over</button>
		</div>
	{/if}
</section>

<style>
	.question {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	h2 {
		margin: 0;
	}
	.eyebrow,
	.meta {
		margin: 0;
		opacity: 0.65;
		font-size: 0.9em;
	}
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.5rem 1rem;
		margin: 0;
	}
	dt {
		opacity: 0.6;
	}
	dd {
		margin: 0;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
</style>
