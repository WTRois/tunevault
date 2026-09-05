<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve */
	import { onMount, onDestroy } from 'svelte';
	import { ApiError } from '$lib/api/client';
	import { toast } from '$lib/stores/toast.svelte';
	import {
		preview,
		applyPlans,
		undoChangeSet,
		listChangeSets,
		isActionable,
		type ChangeSetSummary,
		type OrganizationPlan
	} from '$lib/api/organization';
	import { watchJob } from '$lib/utils/jobProgress.svelte';
	import { FolderTree, RefreshCw, Play, Undo2, ArrowDown } from '@lucide/svelte';

	let plans = $state<OrganizationPlan[]>([]);
	let dryRun = $state(false);
	let loading = $state(true);
	let emptyLibrary = $state(false);
	let changeSets = $state<ChangeSetSummary[]>([]);
	let applying = $state(false);
	let undoingId = $state<number | null>(null);
	let activeJob = $state<{ id: number; progress: number; kind: 'apply' | 'undo' } | null>(null);
	let cancelWatcher: (() => void) | null = null;

	onDestroy(() => cancelWatcher?.());

	const actionable = $derived(plans.filter(isActionable));
	const skippedCount = $derived(plans.filter((p) => p.skipped).length);
	const errorCount = $derived(plans.filter((p) => p.error).length);

	onMount(() => {
		void refresh();
	});

	async function refresh() {
		await Promise.all([loadPreview(), loadHistory()]);
	}

	async function loadPreview() {
		loading = true;
		emptyLibrary = false;
		try {
			const res = await preview({ all: true });
			plans = res.plans;
			dryRun = res.dry_run;
		} catch (err) {
			if (err instanceof ApiError && err.status === 400) {
				// "No files to preview." — nothing has been identified yet.
				emptyLibrary = true;
				plans = [];
			} else {
				toast.error((err as Error).message || 'Failed to build change plans');
			}
		} finally {
			loading = false;
		}
	}

	async function loadHistory() {
		try {
			changeSets = await listChangeSets();
		} catch (err) {
			toast.error((err as Error).message || 'Failed to load change set history');
		}
	}

	async function applyAll() {
		applying = true;
		try {
			const res = await applyPlans({ all: true });
			toast.info(`Organize job queued (${res.queued_files} files)`);
			trackJob(res.job_id, 'apply');
		} catch (err) {
			toast.error((err as Error).message || 'Failed to start organize job');
			applying = false;
		}
	}

	async function undo(changeSetId: number) {
		undoingId = changeSetId;
		try {
			const res = await undoChangeSet(changeSetId);
			toast.info('Undo job queued');
			trackJob(res.job_id, 'undo');
		} catch (err) {
			toast.error((err as Error).message || 'Failed to start undo job');
			undoingId = null;
		}
	}

	function trackJob(jobId: number, kind: 'apply' | 'undo') {
		activeJob = { id: jobId, progress: 0, kind };
		cancelWatcher?.();
		cancelWatcher = watchJob(
			jobId,
			(event) => {
				if (event.type === 'job.progress') {
					if (event.percent != null && activeJob) {
						activeJob = { ...activeJob, progress: event.percent };
					}
					return;
				}
				activeJob = null;
				applying = false;
				undoingId = null;
				if (event.type === 'job.completed') {
					toast.success(kind === 'apply' ? 'Files organized' : 'Change set rolled back');
					void refresh();
				} else {
					toast.error(event.error_message || 'Organize job failed');
					void loadHistory();
				}
			},
			(message) => {
				activeJob = null;
				applying = false;
				undoingId = null;
				toast.error(message);
			}
		);
	}

	function fmt(value: unknown): string {
		return value === null || value === undefined || value === '' ? '—' : String(value);
	}

	function confPct(confidence: number): string {
		return `${Math.round((confidence ?? 0) * 100)}%`;
	}

	function confClass(confidence: number): string {
		if (confidence >= 0.8) return 'bg-emerald-100 text-emerald-800';
		if (confidence >= 0.5) return 'bg-amber-100 text-amber-800';
		return 'bg-stone-100 text-stone-600';
	}

	function statusClass(status: string): string {
		switch (status) {
			case 'applied':
				return 'bg-emerald-100 text-emerald-800';
			case 'partial':
				return 'bg-amber-100 text-amber-800';
			case 'failed':
			case 'rollback_failed':
				return 'bg-red-100 text-red-800';
			case 'rolled_back':
				return 'bg-sky-100 text-sky-800';
			case 'dry_run':
				return 'bg-stone-200 text-stone-700';
			default:
				return 'bg-stone-100 text-stone-500';
		}
	}

	function canUndo(status: string): boolean {
		return status === 'applied' || status === 'partial' || status === 'failed';
	}
</script>

<div class="mx-auto w-full max-w-6xl space-y-6 p-6">
	<header class="flex items-center gap-3">
		<FolderTree class="h-6 w-6 text-[#C97B45]" />
		<div>
			<h1 class="flex items-center gap-2 text-2xl font-bold text-stone-900">
				Organize
				{#if dryRun}
					<span class="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
						DRY RUN
					</span>
				{/if}
			</h1>
			<p class="text-sm text-stone-500">
				Review the plan, then let the worker apply it — every file is backed up first and every
				change set can be undone.
			</p>
		</div>
	</header>

	{#if activeJob}
		<section class="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
			<div class="mb-2 flex items-center justify-between text-sm">
				<span class="font-medium text-stone-800">
					{activeJob.kind === 'apply' ? 'Applying changes…' : 'Rolling back…'}
				</span>
				<span class="text-stone-500">{Math.round(activeJob.progress)}%</span>
			</div>
			<div class="h-2 w-full overflow-hidden rounded-full bg-stone-200">
				<div
					class="h-full rounded-full bg-[#C97B45] transition-all"
					style={`width: ${activeJob.progress}%`}
				></div>
			</div>
			<p class="mt-2 text-xs text-stone-400">
				Jobs run in the TuneVault worker — if progress stalls, make sure the worker is running.
			</p>
		</section>
	{/if}

	<!-- Plan review -->
	<section class="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
		<div class="mb-3 flex items-center justify-between">
			<h2 class="text-sm font-semibold text-stone-900">Proposed changes ({actionable.length})</h2>
			<div class="flex items-center gap-2">
				<button
					class="flex items-center gap-1 rounded-lg bg-stone-200 px-3 py-1.5 text-xs font-medium text-stone-700 hover:bg-stone-300 disabled:opacity-50"
					disabled={loading || activeJob !== null}
					onclick={() => loadPreview()}
				>
					<RefreshCw class="h-3.5 w-3.5" />
					Refresh
				</button>
				<button
					class="flex items-center gap-1 rounded-lg bg-[#C97B45] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#b06a38] disabled:opacity-50"
					disabled={applying || activeJob !== null || actionable.length === 0}
					onclick={() => applyAll()}
				>
					<Play class="h-3.5 w-3.5" />
					{applying ? 'Applying…' : 'Apply all'}
				</button>
			</div>
		</div>

		{#if loading}
			<p class="p-4 text-sm text-stone-500">Building change plans…</p>
		{:else if emptyLibrary}
			<p class="p-4 text-sm text-stone-500">
				Nothing to organize yet — <a class="text-[#C97B45] underline" href="/identify"
					>identify some files first</a
				>.
			</p>
		{:else if actionable.length === 0}
			<p class="p-4 text-sm text-stone-500">
				No pending changes — your library already matches the plan.
			</p>
		{:else}
			<div class="overflow-x-auto">
				<table class="w-full text-left text-sm">
					<thead>
						<tr class="border-b border-stone-200 text-xs text-stone-500 uppercase">
							<th class="py-2 pr-4">File</th>
							<th class="py-2 pr-4">Metadata changes</th>
							<th class="py-2">Confidence</th>
						</tr>
					</thead>
					<tbody>
						{#each actionable as plan (plan.file_id)}
							<tr class="border-b border-stone-100 last:border-0">
								<td class="py-3 pr-4">
									<p class="text-xs break-all text-stone-500">{plan.old_path}</p>
									<p
										class="mt-1 flex items-start gap-1 text-xs font-medium break-all text-stone-800"
									>
										<ArrowDown class="mt-0.5 h-3 w-3 shrink-0 text-[#C97B45]" />
										{plan.new_path}
									</p>
								</td>
								<td class="py-3 pr-4">
									{#if plan.metadata_changes}
										<ul class="space-y-0.5">
											{#each Object.entries(plan.metadata_changes) as [field, [oldValue, newValue]] (field)}
												<li class="text-xs">
													<span class="font-medium text-stone-700 capitalize">
														{field.replace(/_/g, ' ')}
													</span>:
													<span class="text-stone-500">{fmt(oldValue)}</span>
													→
													<span class="text-emerald-700">{fmt(newValue)}</span>
												</li>
											{/each}
										</ul>
									{:else}
										<span class="text-xs text-stone-400">—</span>
									{/if}
								</td>
								<td class="py-3">
									<span
										class="rounded-full px-2 py-0.5 text-xs font-medium {confClass(
											plan.confidence ?? 0
										)}"
									>
										{confPct(plan.confidence ?? 0)}
									</span>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{#if skippedCount > 0 || errorCount > 0}
				<p class="mt-3 text-xs text-stone-400">
					{skippedCount} skipped (no accepted metadata){#if errorCount > 0}
						· {errorCount} errors{/if}
				</p>
			{/if}
		{/if}
	</section>

	<!-- History -->
	<section class="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
		<h2 class="mb-3 text-sm font-semibold text-stone-900">Change set history</h2>
		{#if changeSets.length === 0}
			<p class="p-4 text-sm text-stone-500">No change sets yet.</p>
		{:else}
			<div class="overflow-x-auto">
				<table class="w-full text-left text-sm">
					<thead>
						<tr class="border-b border-stone-200 text-xs text-stone-500 uppercase">
							<th class="py-2 pr-4">Name</th>
							<th class="py-2 pr-4">Status</th>
							<th class="py-2 pr-4">Created</th>
							<th class="py-2 pr-4">Applied</th>
							<th class="py-2"></th>
						</tr>
					</thead>
					<tbody>
						{#each changeSets as cs (cs.id)}
							<tr class="border-b border-stone-100 last:border-0">
								<td class="py-3 pr-4">
									<p class="font-medium text-stone-800">{cs.name}</p>
									<p class="text-xs text-stone-400">#{cs.id}</p>
								</td>
								<td class="py-3 pr-4">
									<span
										class="rounded-full px-2 py-0.5 text-xs font-medium {statusClass(cs.status)}"
									>
										{cs.status.replace(/_/g, ' ')}
									</span>
								</td>
								<td class="py-3 pr-4 text-xs text-stone-500">
									{new Date(cs.created_at).toLocaleString()}
								</td>
								<td class="py-3 pr-4 text-xs text-stone-500">
									{cs.applied_at ? new Date(cs.applied_at).toLocaleString() : '—'}
								</td>
								<td class="py-3 text-right">
									{#if canUndo(cs.status)}
										<button
											class="flex items-center gap-1 rounded-lg bg-stone-200 px-3 py-1.5 text-xs font-medium text-stone-700 hover:bg-stone-300 disabled:opacity-50"
											disabled={activeJob !== null || undoingId !== null}
											onclick={() => undo(cs.id)}
										>
											<Undo2 class="h-3.5 w-3.5" />
											{undoingId === cs.id ? 'Undoing…' : 'Undo'}
										</button>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>
</div>
