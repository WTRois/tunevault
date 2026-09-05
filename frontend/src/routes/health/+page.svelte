<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from '$lib/stores/toast.svelte';
	import {
		getLibraryHealth,
		getIssueRows,
		getDuplicatePairs,
		type LibraryHealth,
		type IssueType,
		type IssueRow,
		type DuplicatePair
	} from '$lib/api/health';
	import { Activity, RefreshCw, ChevronDown, ChevronUp, CheckCircle2 } from '@lucide/svelte';

	let health = $state<LibraryHealth | null>(null);
	let loading = $state(true);
	let openIssue = $state<IssueType | null>(null);
	let rows = $state<IssueRow[]>([]);
	let pairs = $state<DuplicatePair[]>([]);
	let rowsLoading = $state(false);

	const issueMeta: Record<IssueType, { label: string; description: string; action: string }> = {
		unidentified: {
			label: 'Unidentified',
			description: 'Files not yet linked to a known recording.',
			action: 'Review'
		},
		missing_artwork: {
			label: 'Missing artwork',
			description: 'Files without embedded or release artwork.',
			action: 'Fix'
		},
		duplicates: {
			label: 'Duplicates',
			description: 'Exact or audio duplicate pairs.',
			action: 'Review'
		},
		inconsistent_album_artist: {
			label: 'Inconsistent album artist',
			description: 'Albums where files disagree on the album artist.',
			action: 'Review'
		},
		possible_upsample: {
			label: 'Possible upsample',
			description: 'Files whose spectral ceiling suggests upsampled audio.',
			action: 'Inspect'
		}
	};

	const scores = $derived([
		{
			label: 'Metadata',
			value: health?.metadata_health ?? 0,
			caption: `${health?.issues.inconsistent_album_artist ?? 0} inconsistent album artists`
		},
		{
			label: 'Identification',
			value: health?.identification_health ?? 0,
			caption: `${health?.issues.unidentified ?? 0} unidentified files`
		},
		{
			label: 'Artwork',
			value: health?.artwork_health ?? 0,
			caption: `${health?.issues.missing_artwork ?? 0} files missing artwork`
		},
		{
			label: 'Audio Analysis',
			value: health?.audio_analysis_health ?? 0,
			caption: `${health?.issues.possible_upsample ?? 0} possible upsamples`
		},
		{
			label: 'Duplicates',
			value: health?.duplicate_health ?? 0,
			caption: `${health?.issues.duplicates ?? 0} duplicate pairs`
		}
	]);

	const issues = $derived(
		(Object.keys(issueMeta) as IssueType[]).map((type) => ({
			type,
			count: health?.issues[type] ?? 0,
			...issueMeta[type]
		}))
	);

	const allHealthy = $derived(
		health !== null && issues.every((i) => i.count === 0) && scores.every((s) => s.value >= 100)
	);

	onMount(() => {
		void refresh();
	});

	async function refresh() {
		loading = true;
		openIssue = null;
		rows = [];
		pairs = [];
		try {
			health = await getLibraryHealth();
		} catch (err) {
			toast.error((err as Error).message || 'Failed to load library health');
		} finally {
			loading = false;
		}
	}

	async function toggleIssue(type: IssueType) {
		if (openIssue === type) {
			openIssue = null;
			rows = [];
			pairs = [];
			return;
		}
		openIssue = type;
		rows = [];
		pairs = [];
		rowsLoading = true;
		try {
			if (type === 'duplicates') {
				pairs = await getDuplicatePairs();
			} else {
				rows = await getIssueRows(type);
			}
		} catch (err) {
			toast.error((err as Error).message || 'Failed to load issue details');
		} finally {
			rowsLoading = false;
		}
	}

	function scoreBarColor(value: number): string {
		if (value >= 90) return 'bg-emerald-500';
		if (value >= 70) return 'bg-amber-500';
		return 'bg-red-500';
	}

	function scoreTextColor(value: number): string {
		if (value >= 90) return 'text-emerald-600';
		if (value >= 70) return 'text-amber-600';
		return 'text-red-600';
	}

	function dupClass(classification: string): string {
		switch (classification) {
			case 'EXACT_FILE_DUPLICATE':
				return 'bg-red-100 text-red-800';
			case 'AUDIO_DUPLICATE':
				return 'bg-amber-100 text-amber-800';
			case 'SAME_RECORDING_DIFFERENT_FORMAT':
				return 'bg-stone-100 text-stone-600';
			default:
				return 'bg-stone-200 text-stone-700';
		}
	}

	function rowDetail(row: IssueRow): string {
		if (openIssue === 'inconsistent_album_artist') {
			return `Album "${row.album ?? '—'}": expected "${row.expected_album_artist ?? '—'}", actual "${row.actual_album_artist ?? '—'}"`;
		}
		if (openIssue === 'possible_upsample') {
			const rate = ((row.sample_rate ?? 0) / 1000).toFixed(1);
			const ceiling = Math.round((row.frequency_ceiling_hz ?? 0) / 1000);
			return `${rate} kHz file, spectral ceiling ~${ceiling} kHz (${row.confidence ?? '—'})`;
		}
		return row.title ?? 'No title';
	}
</script>

<div class="mx-auto w-full max-w-6xl space-y-6 p-6">
	<header class="flex items-center gap-3">
		<Activity class="h-6 w-6 text-[#C97B45]" />
		<div class="flex-1">
			<h1 class="text-2xl font-bold text-stone-900">Library Health</h1>
			<p class="text-sm text-stone-500">
				Five health scores and actionable issues across your library.
			</p>
		</div>
		<button
			class="flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-xs font-medium text-stone-600 hover:bg-stone-50 disabled:opacity-50"
			disabled={loading}
			onclick={() => void refresh()}
		>
			<RefreshCw class="h-3.5 w-3.5 {loading ? 'animate-spin' : ''}" />
			Refresh
		</button>
	</header>

	{#if loading}
		<section class="rounded-2xl border border-stone-200 bg-white p-8 text-center shadow-sm">
			<RefreshCw class="mx-auto h-5 w-5 animate-spin text-stone-400" />
			<p class="mt-2 text-sm text-stone-500">Loading library health…</p>
		</section>
	{:else if health}
		<!-- Score cards -->
		<section class="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
			{#each scores as s (s.label)}
				<div class="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
					<p class="text-xs font-medium tracking-wide text-stone-500 uppercase">{s.label}</p>
					<p class="mt-1 text-2xl font-bold {scoreTextColor(s.value)}">
						{Math.round(s.value)}%
					</p>
					<div class="mt-2 h-2 w-full overflow-hidden rounded-full bg-stone-200">
						<div
							class="h-full rounded-full {scoreBarColor(s.value)} transition-all"
							style={`width: ${Math.min(s.value, 100)}%`}
						></div>
					</div>
					<p class="mt-2 text-xs text-stone-400">{s.caption}</p>
				</div>
			{/each}
		</section>

		<!-- Issues -->
		<section class="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
			<h2 class="mb-3 text-sm font-semibold text-stone-900">Issues</h2>
			{#if allHealthy}
				<div class="flex items-center gap-2 py-6 text-sm text-emerald-700">
					<CheckCircle2 class="h-5 w-5 text-emerald-500" />
					Library is healthy — no issues found.
				</div>
			{:else}
				{#each issues as issue (issue.type)}
					{#if issue.count > 0}
						<div class="flex items-center justify-between gap-4 border-t border-stone-100 py-3">
							<div>
								<p class="flex items-center gap-2 text-sm font-medium text-stone-800">
									{issue.label}
									<span
										class="rounded-full bg-stone-100 px-2 py-0.5 text-xs font-semibold text-stone-600"
									>
										{issue.count}
									</span>
								</p>
								<p class="text-xs text-stone-400">{issue.description}</p>
							</div>
							<button
								class="flex shrink-0 items-center gap-1 rounded-lg bg-[#C97B45] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#B36A38]"
								onclick={() => void toggleIssue(issue.type)}
							>
								{issue.action}
								{#if openIssue === issue.type}
									<ChevronUp class="h-3.5 w-3.5" />
								{:else}
									<ChevronDown class="h-3.5 w-3.5" />
								{/if}
							</button>
						</div>
					{/if}
				{/each}

				{#if openIssue !== null}
					<div class="mt-2 overflow-x-auto rounded-xl bg-stone-50 p-3">
						{#if rowsLoading}
							<p class="py-6 text-center text-sm text-stone-400">Loading…</p>
						{:else if openIssue === 'duplicates'}
							{#if pairs.length === 0}
								<p class="py-6 text-center text-sm text-stone-400">No duplicate pairs.</p>
							{:else}
								<table class="w-full text-left text-sm">
									<thead class="text-xs tracking-wide text-stone-400 uppercase">
										<tr>
											<th class="py-2 pr-4">File A</th>
											<th class="py-2 pr-4">File B</th>
											<th class="py-2 pr-4">Classification</th>
											<th class="py-2">Similarity</th>
										</tr>
									</thead>
									<tbody>
										{#each pairs as p (`${p.file_id_a}-${p.file_id_b}`)}
											<tr class="border-t border-stone-100">
												<td class="py-2.5 pr-4 text-stone-800" title={p.path_a}>
													{p.filename_a}
												</td>
												<td class="py-2.5 pr-4 text-stone-800" title={p.path_b}>
													{p.filename_b}
												</td>
												<td class="py-2.5 pr-4">
													<span
														class="rounded-full px-2 py-0.5 text-xs font-semibold {dupClass(
															p.classification
														)}"
													>
														{p.classification.replace(/_/g, ' ')}
													</span>
												</td>
												<td class="py-2.5 text-stone-600">
													{p.similarity !== null ? `${Math.round(p.similarity * 100)}%` : '—'}
												</td>
											</tr>
										{/each}
									</tbody>
								</table>
							{/if}
						{:else}
							{#if rows.length === 0}
								<p class="py-6 text-center text-sm text-stone-400">No affected files.</p>
							{:else}
								<table class="w-full text-left text-sm">
									<thead class="text-xs tracking-wide text-stone-400 uppercase">
										<tr>
											<th class="py-2 pr-4">File</th>
											<th class="py-2 pr-4">Detail</th>
											<th class="py-2">Path</th>
										</tr>
									</thead>
									<tbody>
										{#each rows as r (r.file_id)}
											<tr class="border-t border-stone-100">
												<td class="py-2.5 pr-4 text-stone-800">{r.filename}</td>
												<td class="py-2.5 pr-4 text-stone-600">{rowDetail(r)}</td>
												<td class="py-2.5 text-xs text-stone-400">{r.filepath}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							{/if}
						{/if}
					</div>
				{/if}
			{/if}
		</section>
	{/if}
</div>
