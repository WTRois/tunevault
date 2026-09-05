<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { api } from '$lib/api/client';
	import { toast } from '$lib/stores/toast.svelte';
	import { watchJob, type JobProgressEvent } from '$lib/utils/jobProgress.svelte';
	import {
		getSongCandidates,
		startIdentificationJob,
		acceptCandidate,
		rejectCandidate,
		getReviewQueue,
		bulkAccept,
		getReleasePreferences,
		updateReleasePreferences,
		type IdentificationCandidate,
		type ReleasePreferences,
		type ReviewCandidate
	} from '$lib/api/identification';
	import {
		Search,
		Check,
		X,
		Sparkles,
		CheckCheck,
		Layers,
		ListChecks,
		SlidersHorizontal
	} from '@lucide/svelte';

	interface Song {
		id: number;
		filename: string;
		filepath: string;
		title?: string | null;
		artist?: string | null;
		album?: string | null;
	}

	let songs = $state<Song[]>([]);
	let loading = $state(true);
	let search = $state('');
	let selectedSongId = $state<number | null>(null);
	let candidates = $state<IdentificationCandidate[]>([]);
	let candidatesLoading = $state(false);
	let identifying = $state(false);
	let acceptingId = $state<number | null>(null);
	let jobEvent = $state<JobProgressEvent | null>(null);
	let cancelWatcher: (() => void) | null = null;

	// Review queue (§22): pending candidates across all files.
	let reviewItems = $state<ReviewCandidate[]>([]);
	let reviewFilter = $state('');
	let reviewLoading = $state(false);
	let selectedIds = $state<number[]>([]);
	let bulkWorking = $state(false);

	// Release preferences (§10).
	let prefs = $state<ReleasePreferences | null>(null);
	let prefsSaving = $state(false);
	const PREFERENCE_OPTIONS = [
		{ value: 'prefer_original', label: 'Prefer original releases' },
		{ value: 'prefer_remaster', label: 'Prefer remasters' },
		{ value: 'prefer_high_res', label: 'Prefer high-res releases' },
		{ value: 'prefer_specific_country', label: 'Prefer specific country' },
		{ value: 'prefer_specific_label', label: 'Prefer specific label' }
	];

	onDestroy(() => cancelWatcher?.());

	const filteredSongs = $derived(
		search.trim()
			? songs.filter((s) =>
					`${s.title ?? ''} ${s.artist ?? ''} ${s.filename}`
						.toLowerCase()
						.includes(search.toLowerCase())
				)
			: songs
	);

	onMount(async () => {
		await loadSongs();
		await Promise.all([loadReview(), loadPrefs()]);
	});

	async function loadSongs() {
		loading = true;
		try {
			const data = await api.get<{ items: Song[]; total: number }>('/songs?limit=200');
			songs = data.items;
		} catch (err) {
			toast.error((err as Error).message || 'Failed to load songs');
		} finally {
			loading = false;
		}
	}

	async function selectSong(songId: number) {
		selectedSongId = songId;
		await loadCandidates();
	}

	async function loadCandidates() {
		if (!selectedSongId) return;
		candidatesLoading = true;
		try {
			candidates = await getSongCandidates(selectedSongId);
		} catch (err) {
			toast.error((err as Error).message || 'Failed to load candidates');
		} finally {
			candidatesLoading = false;
		}
	}

	async function identifySong(songId: number) {
		identifying = true;
		jobEvent = null;
		try {
			const job = await startIdentificationJob([songId]);
			cancelWatcher?.();
			cancelWatcher = watchJob(
				job.id,
				(event) => {
					jobEvent = event;
					if (event.type === 'job.completed') {
						toast.success('Identification finished');
						identifying = false;
						if (selectedSongId === songId) void loadCandidates();
						void loadReview();
					} else if (event.type === 'job.failed') {
						toast.error(event.error_message || 'Identification failed');
						identifying = false;
					}
				},
				(message) => {
					toast.error(message);
					identifying = false;
				}
			);
		} catch (err) {
			toast.error((err as Error).message || 'Identification failed to start');
			identifying = false;
		}
	}

	async function accept(candidateId: number) {
		if (!selectedSongId) return;
		acceptingId = candidateId;
		try {
			await acceptCandidate(selectedSongId, candidateId);
			toast.success('Candidate accepted — canonical metadata saved');
			await loadCandidates();
		} catch (err) {
			toast.error((err as Error).message || 'Failed to accept candidate');
		} finally {
			acceptingId = null;
		}
	}

	async function reject(candidateId: number) {
		if (!selectedSongId) return;
		try {
			await rejectCandidate(selectedSongId, candidateId);
			await loadCandidates();
		} catch (err) {
			toast.error((err as Error).message || 'Failed to reject candidate');
		}
	}

	function scoreColor(level: string): string {
		switch (level) {
			case 'auto_apply':
				return 'bg-emerald-100 text-emerald-800';
			case 'auto_suggest_review':
				return 'bg-sky-100 text-sky-800';
			case 'review_required':
				return 'bg-amber-100 text-amber-800';
			default:
				return 'bg-stone-200 text-stone-700';
		}
	}

	async function loadReview() {
		reviewLoading = true;
		try {
			reviewItems = await getReviewQueue({
				confidence_level: reviewFilter || undefined
			});
			selectedIds = selectedIds.filter((id) => reviewItems.some((item) => item.id === id));
		} catch (err) {
			toast.error((err as Error).message || 'Failed to load review queue');
		} finally {
			reviewLoading = false;
		}
	}

	function toggleSelect(id: number) {
		selectedIds = selectedIds.includes(id)
			? selectedIds.filter((x) => x !== id)
			: [...selectedIds, id];
	}

	async function bulkAcceptSelected() {
		if (selectedIds.length === 0 || bulkWorking) return;
		bulkWorking = true;
		try {
			const res = await bulkAccept({ candidate_ids: selectedIds });
			toast.success(`Accepted ${res.accepted.length} candidate(s), skipped ${res.skipped}`);
			for (const message of res.errors) toast.error(message);
			selectedIds = [];
			await loadReview();
		} catch (err) {
			toast.error((err as Error).message || 'Bulk accept failed');
		} finally {
			bulkWorking = false;
		}
	}

	async function bulkAcceptAllMatching() {
		if (bulkWorking) return;
		bulkWorking = true;
		try {
			const res = await bulkAccept({
				confidence_level: reviewFilter || undefined
			});
			toast.success(
				`Accepted ${res.accepted.length} best candidate(s) per file, skipped ${res.skipped}`
			);
			for (const message of res.errors) toast.error(message);
			selectedIds = [];
			await loadReview();
		} catch (err) {
			toast.error((err as Error).message || 'Bulk accept failed');
		} finally {
			bulkWorking = false;
		}
	}

	async function loadPrefs() {
		try {
			prefs = await getReleasePreferences();
		} catch (err) {
			toast.error((err as Error).message || 'Failed to load release preferences');
		}
	}

	async function savePrefs() {
		if (!prefs || prefsSaving) return;
		prefsSaving = true;
		try {
			prefs = await updateReleasePreferences(prefs);
			toast.success('Release preferences saved');
		} catch (err) {
			toast.error((err as Error).message || 'Failed to save release preferences');
		} finally {
			prefsSaving = false;
		}
	}
</script>

<div class="mx-auto w-full max-w-6xl space-y-6 p-6">
	<header class="flex items-center gap-3">
		<Sparkles class="h-6 w-6 text-[#C97B45]" />
		<div>
			<h1 class="text-2xl font-bold text-stone-900">Identify</h1>
			<p class="text-sm text-stone-500">
				Match your files to canonical MusicBrainz recordings — nothing is written to your files.
			</p>
		</div>
	</header>

	<div class="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
		<!-- Song picker -->
		<section class="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm">
			<div class="relative mb-3">
				<Search class="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-stone-400" />
				<input
					type="text"
					bind:value={search}
					placeholder="Search songs…"
					class="w-full rounded-xl border border-stone-200 py-2 pr-3 pl-9 text-sm focus:border-[#C97B45] focus:outline-none"
				/>
			</div>
			{#if loading}
				<p class="p-4 text-sm text-stone-500">Loading songs…</p>
			{:else if filteredSongs.length === 0}
				<p class="p-4 text-sm text-stone-500">No songs found.</p>
			{:else}
				<ul class="max-h-[28rem] space-y-1 overflow-y-auto pr-1">
					{#each filteredSongs as song (song.id)}
						<li>
							<button
								class={`w-full rounded-xl px-3 py-2 text-left text-sm transition-colors ${
									selectedSongId === song.id
										? 'bg-[#C97B45] font-medium text-white'
										: 'text-stone-700 hover:bg-stone-100'
								}`}
								onclick={() => selectSong(song.id)}
							>
								<span class="block truncate">{song.title || song.filename}</span>
								<span
									class={`block truncate text-xs ${selectedSongId === song.id ? 'text-white/80' : 'text-stone-500'}`}
								>
									{song.artist || 'Unknown artist'}
								</span>
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</section>

		<!-- Candidates panel -->
		<section class="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
			{#if !selectedSongId}
				<p class="py-16 text-center text-sm text-stone-500">
					Pick a song on the left, then run identification.
				</p>
			{:else}
				<div class="mb-4 flex items-center justify-between">
					<h2 class="text-lg font-semibold text-stone-900">Candidates</h2>
					<button
						class="flex items-center gap-2 rounded-xl bg-[#C97B45] px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-[#b36a38] disabled:opacity-50"
						disabled={identifying}
						onclick={() => {
							if (selectedSongId !== null) identifySong(selectedSongId);
						}}
					>
						<Sparkles class="h-4 w-4" />
						{#if identifying}
							{jobEvent?.percent != null
								? `Identifying… ${Math.round(jobEvent.percent)}%`
								: 'Identifying…'}
						{:else}
							Identify
						{/if}
					</button>
				</div>

				{#if identifying && jobEvent?.current_file}
					<p class="mb-2 truncate text-xs text-stone-400">{jobEvent.current_file}</p>
				{/if}

				{#if candidatesLoading}
					<p class="py-8 text-center text-sm text-stone-500">Loading candidates…</p>
				{:else if candidates.length === 0}
					<p class="py-8 text-center text-sm text-stone-500">
						No candidates yet — run identification to search MusicBrainz &amp; AcoustID.
					</p>
				{:else}
					<ul class="space-y-3">
						{#each candidates as candidate (candidate.id)}
							<li class="rounded-xl border border-stone-200 p-4">
								<div class="flex items-start justify-between gap-3">
									<div class="min-w-0">
										<p class="truncate font-medium text-stone-900">
											{candidate.title || 'Unknown title'}
										</p>
										<p class="truncate text-sm text-stone-500">
											{candidate.artist || 'Unknown artist'}
										</p>
										{#if candidate.release_title}
											<p class="truncate text-xs text-stone-400">{candidate.release_title}</p>
										{/if}
										<p class="mt-1 text-xs text-stone-400">via {candidate.source}</p>
									</div>
									<span
										class={`shrink-0 rounded-full px-2 py-1 text-xs font-semibold ${scoreColor(candidate.confidence_level)}`}
									>
										{candidate.score.toFixed(1)}
									</span>
								</div>
								{#if candidate.status === 'pending'}
									<div class="mt-3 flex gap-2">
										<button
											class="flex flex-1 items-center justify-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
											disabled={acceptingId === candidate.id}
											onclick={() => accept(candidate.id)}
										>
											<Check class="h-3.5 w-3.5" />
											{acceptingId === candidate.id ? 'Accepting…' : 'Accept'}
										</button>
										<button
											class="flex flex-1 items-center justify-center gap-1 rounded-lg bg-stone-200 px-3 py-1.5 text-xs font-medium text-stone-700 hover:bg-stone-300"
											onclick={() => reject(candidate.id)}
										>
											<X class="h-3.5 w-3.5" />
											Reject
										</button>
									</div>
								{:else}
									<p class="mt-3 text-xs font-medium text-stone-500 uppercase">
										{candidate.status}
									</p>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			{/if}
		</section>
	</div>

	<!-- Review queue (§22): pending candidates across all files -->
	<section class="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
		<div class="mb-4 flex flex-wrap items-center gap-3">
			<h2 class="flex items-center gap-2 text-lg font-semibold text-stone-900">
				<ListChecks class="h-5 w-5 text-[#C97B45]" />
				Review queue
			</h2>
			<span class="rounded-full bg-stone-100 px-2 py-0.5 text-xs font-medium text-stone-600">
				{reviewItems.length} pending
			</span>
			<select
				class="ml-auto rounded-xl border border-stone-200 px-3 py-2 text-sm focus:border-[#C97B45] focus:outline-none"
				bind:value={reviewFilter}
				onchange={() => loadReview()}
			>
				<option value="">All confidence levels</option>
				<option value="auto_apply">Auto apply</option>
				<option value="auto_suggest_review">Suggest review</option>
				<option value="review_required">Review required</option>
				<option value="no_match">No match</option>
			</select>
			<button
				class="flex items-center gap-1.5 rounded-xl bg-stone-200 px-3 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-300 disabled:opacity-50"
				disabled={bulkWorking || selectedIds.length === 0}
				onclick={bulkAcceptSelected}
			>
				<CheckCheck class="h-4 w-4" />
				Accept selected ({selectedIds.length})
			</button>
			<button
				class="flex items-center gap-1.5 rounded-xl bg-[#C97B45] px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-[#b36a38] disabled:opacity-50"
				disabled={bulkWorking || reviewItems.length === 0}
				onclick={bulkAcceptAllMatching}
			>
				<Layers class="h-4 w-4" />
				Accept best per file
			</button>
		</div>

		{#if reviewLoading}
			<p class="py-6 text-center text-sm text-stone-500">Loading review queue…</p>
		{:else if reviewItems.length === 0}
			<p class="py-6 text-center text-sm text-stone-500">
				No pending candidates — run identification to fill the queue.
			</p>
		{:else}
			<div class="overflow-x-auto">
				<table class="w-full text-left text-sm">
					<thead>
						<tr class="border-b border-stone-200 text-xs text-stone-500 uppercase">
							<th class="w-10 py-2 pr-2"></th>
							<th class="py-2 pr-4">Candidate</th>
							<th class="py-2 pr-4">File</th>
							<th class="py-2 pr-4">Source</th>
							<th class="py-2 text-right">Score</th>
						</tr>
					</thead>
					<tbody>
						{#each reviewItems as item (item.id)}
							<tr class="border-b border-stone-100 last:border-0">
								<td class="py-2 pr-2 align-top">
									<input
										type="checkbox"
										class="h-4 w-4 accent-[#C97B45]"
										checked={selectedIds.includes(item.id)}
										onchange={() => toggleSelect(item.id)}
									/>
								</td>
								<td class="py-2 pr-4">
									<p class="max-w-[16rem] truncate font-medium text-stone-900">
										{item.title || 'Unknown title'}
									</p>
									<p class="max-w-[16rem] truncate text-xs text-stone-500">
										{item.artist || 'Unknown artist'}
									</p>
								</td>
								<td class="max-w-[18rem] truncate py-2 pr-4 text-xs text-stone-500"
									>{item.filename}</td
								>
								<td class="py-2 pr-4 text-xs text-stone-500">{item.source}</td>
								<td class="py-2 text-right">
									<span
										class={`rounded-full px-2 py-1 text-xs font-semibold ${scoreColor(item.confidence_level)}`}
										>{item.score.toFixed(1)}</span
									>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>

	<!-- Release preferences (§10) -->
	<section class="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
		<div class="mb-4 flex items-center gap-2">
			<SlidersHorizontal class="h-5 w-5 text-[#C97B45]" />
			<h2 class="text-lg font-semibold text-stone-900">Release preferences</h2>
		</div>
		{#if prefs}
			<div class="grid gap-4 md:grid-cols-3">
				<label class="text-sm">
					<span class="mb-1 block font-medium text-stone-700">Preference</span>
					<select
						class="w-full rounded-xl border border-stone-200 px-3 py-2 text-sm focus:border-[#C97B45] focus:outline-none"
						bind:value={prefs.preference}
					>
						{#each PREFERENCE_OPTIONS as option (option.value)}
							<option value={option.value}>{option.label}</option>
						{/each}
					</select>
				</label>
				<label class="text-sm">
					<span class="mb-1 block font-medium text-stone-700">Country (for specific country)</span>
					<input
						type="text"
						placeholder="e.g. US, JP"
						class="w-full rounded-xl border border-stone-200 px-3 py-2 text-sm focus:border-[#C97B45] focus:outline-none"
						bind:value={prefs.country}
					/>
				</label>
				<label class="text-sm">
					<span class="mb-1 block font-medium text-stone-700">Label (for specific label)</span>
					<input
						type="text"
						placeholder="e.g. Mobile Fidelity"
						class="w-full rounded-xl border border-stone-200 px-3 py-2 text-sm focus:border-[#C97B45] focus:outline-none"
						bind:value={prefs.label}
					/>
				</label>
			</div>
			<button
				class="mt-4 flex items-center gap-2 rounded-xl bg-[#C97B45] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#b36a38] disabled:opacity-50"
				disabled={prefsSaving}
				onclick={savePrefs}
			>
				<Check class="h-4 w-4" />
				{prefsSaving ? 'Saving…' : 'Save preferences'}
			</button>
		{:else}
			<p class="py-4 text-sm text-stone-500">Loading release preferences…</p>
		{/if}
	</section>
</div>
