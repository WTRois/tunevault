<script lang="ts">
	/* eslint-disable @typescript-eslint/no-unused-vars */
	import { onMount } from 'svelte';
	import { api, API_BASE_URL, ApiError } from '$lib/api/client';
	import { toast } from '$lib/stores/toast.svelte';
	import { player } from '$lib/stores/player.svelte';
	import { getDefaultMusicDirectory, formatDuration, formatBytes } from '$lib/utils/os';
	import {
		Music,
		Users,
		Disc,
		Clock,
		HardDrive,
		FolderPlus,
		Play,
		Sparkles,
		Music2
	} from '@lucide/svelte';

	interface Stats {
		total_songs: number;
		total_artists: number;
		total_albums: number;
		total_genres: number;
		total_duration: number;
		total_file_size: number;
		codecs: Record<string, number>;
	}

	interface ScanJob {
		id: number;
		directory_path: string;
		status: string;
		scanned_files: number;
		total_files: number;
		added_count: number;
		updated_count: number;
		error_count: number;
		error_message?: string;
	}

	interface Song {
		id: number;
		title?: string;
		artist?: string;
		album?: string;
		duration?: number;
		filename: string;
		sha256: string;
	}

	let stats = $state<Stats | null>(null);
	let recentJobs = $state<ScanJob[]>([]);
	let recentSongs = $state<Song[]>([]);
	let activeJob = $state<ScanJob | null>(null);
	let loading = $state(true);

	// Scan form inputs
	let scanDirectory = $state('');
	let performAudioAnalysis = $state(true);
	let scanLoading = $state(false);

	onMount(async () => {
		scanDirectory = getDefaultMusicDirectory();
		await loadDashboardData();
	});

	async function loadDashboardData() {
		loading = true;
		try {
			const [statsRes, jobsRes, songsRes] = await Promise.all([
				api.get<Stats>('/stats'),
				api.get<ScanJob[]>('/scan/jobs?limit=5'),
				api.get<{ items: Song[] }>('/songs?limit=6&sort_by=id&order=desc')
			]);
			stats = statsRes;
			recentJobs = jobsRes;
			recentSongs = songsRes.items;

			const running = jobsRes.find((j) => j.status === 'running' || j.status === 'pending');
			if (running) {
				activeJob = running;
				pollScanStatus(running.id);
			}
		} catch (err) {
			console.error('Failed to load dashboard data:', err);
		} finally {
			loading = false;
		}
	}

	async function triggerScan() {
		if (!scanDirectory) return;
		scanLoading = true;

		try {
			const job = await api.post<ScanJob>('/scan', {
				directory_path: scanDirectory,
				perform_audio_analysis: performAudioAnalysis
			});
			activeJob = job;
			toast.success(`Scan job #${job.id} started successfully.`);
			pollScanStatus(job.id);

			setTimeout(() => {
				const modal = document.getElementById('scan-modal') as HTMLDialogElement;
				modal?.close();
			}, 800);
		} catch (err: unknown) {
			if (err instanceof ApiError && err.status === 400) {
				toast.error(`${err.message}. (If running inside Docker, use '/music').`);
			} else {
				toast.error((err as Error).message || 'Failed to start scan job');
			}
		} finally {
			scanLoading = false;
		}
	}

	function pollScanStatus(jobId: number) {
		const interval = setInterval(async () => {
			try {
				const updatedJob = await api.get<ScanJob>(`/scan/status/${jobId}`);
				activeJob = updatedJob;

				if (updatedJob.status === 'completed' || updatedJob.status === 'failed') {
					clearInterval(interval);
					activeJob = null;
					await loadDashboardData();
				}
			} catch {
				clearInterval(interval);
			}
		}, 2000);
	}
</script>

<div class="mx-auto max-w-7xl space-y-6">
	<!-- Hero Soft Gradient Banner -->
	<div
		class="hero-gradient relative flex flex-col items-start justify-between gap-6 overflow-hidden rounded-3xl p-8 text-white shadow-2xl md:flex-row md:items-center"
	>
		<div class="z-10 max-w-xl space-y-2">
			<div
				class="inline-flex items-center gap-2 rounded-full bg-white/20 px-3 py-1 text-xs font-semibold backdrop-blur-md"
			>
				<Sparkles class="h-3.5 w-3.5 text-[#D8D66A]" /> Audio Archive
			</div>
			<h1 class="font-mono text-3xl font-extrabold tracking-tight md:text-4xl">
				TuneVault Music Hub
			</h1>
			<p class="text-sm leading-relaxed text-white/80">
				Self-hosted audio metadata indexer, tag writeback engine, and statistics manager.
			</p>
		</div>

		<button
			class="btn z-10 gap-2 rounded-full border-none bg-white px-6 text-sm font-bold text-[#6e4330] shadow-xl hover:bg-[#F9F6F2]"
			onclick={() => {
				const modal = document.getElementById('scan-modal') as HTMLDialogElement;
				modal?.showModal();
			}}
		>
			<FolderPlus class="h-4 w-4 text-[#C97B45]" />
			Scan Music Folder
		</button>
	</div>

	<!-- Active Scan Progress Banner -->
	{#if activeJob}
		<div
			class="glass-panel flex flex-col items-center justify-between gap-4 rounded-2xl border border-[#C97B45]/40 p-4 shadow-lg md:flex-row"
		>
			<div class="flex items-center gap-3">
				<span class="loading loading-md loading-spinner text-[#C97B45]"></span>
				<div>
					<h3 class="text-sm font-bold text-[#2D2724] dark:text-[#F9F6F2]">
						Scan in progress... (Job #{activeJob.id})
					</h3>
					<p class="text-xs text-[#857D78] dark:text-[#D1C9C3]">
						Path: <code class="font-mono">{activeJob.directory_path}</code> | Processed: {activeJob.scanned_files}/{activeJob.total_files ||
							'?'}
					</p>
				</div>
			</div>
			<div class="w-full md:w-48">
				<progress
					class="progress w-full progress-primary"
					value={activeJob.scanned_files}
					max={activeJob.total_files || 100}
				></progress>
			</div>
		</div>
	{/if}

	<!-- Stat Cards -->
	{#if loading}
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
			{#each Array.from({ length: 4 }) as _, idx (idx)}
				<div class="h-32 w-full skeleton rounded-2xl"></div>
			{/each}
		</div>
	{:else if stats}
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
			<div class="glass-card flex items-center justify-between rounded-2xl p-5 shadow-sm">
				<div>
					<span class="block text-xs font-semibold text-[#857D78] dark:text-[#D1C9C3]"
						>Total Tracks</span
					>
					<span class="mt-1 block text-2xl font-extrabold text-[#2D2724] dark:text-[#F9F6F2]"
						>{stats.total_songs}</span
					>
					<span class="text-[11px] font-semibold text-[#5A613B] dark:text-[#C5CC9C]"
						>{stats.total_genres} Genres</span
					>
				</div>
				<div
					class="flex h-12 w-12 items-center justify-center rounded-xl bg-[#C97B45]/15 text-[#C97B45]"
				>
					<Music class="h-6 w-6" />
				</div>
			</div>

			<div class="glass-card flex items-center justify-between rounded-2xl p-5 shadow-sm">
				<div>
					<span class="block text-xs font-semibold text-[#857D78] dark:text-[#D1C9C3]"
						>Artists & Albums</span
					>
					<span class="mt-1 block text-2xl font-extrabold text-[#2D2724] dark:text-[#F9F6F2]"
						>{stats.total_artists}</span
					>
					<span class="text-[11px] font-medium text-[#857D78] dark:text-[#D1C9C3]"
						>{stats.total_albums} Albums</span
					>
				</div>
				<div
					class="flex h-12 w-12 items-center justify-center rounded-xl bg-[#8E9570]/15 text-[#8E9570]"
				>
					<Users class="h-6 w-6" />
				</div>
			</div>

			<div class="glass-card flex items-center justify-between rounded-2xl p-5 shadow-sm">
				<div>
					<span class="block text-xs font-semibold text-[#857D78] dark:text-[#D1C9C3]"
						>Total Duration</span
					>
					<span
						class="mt-1 block font-mono text-2xl font-extrabold text-[#2D2724] dark:text-[#F9F6F2]"
						>{formatDuration(stats.total_duration)}</span
					>
					<span class="text-[11px] font-medium text-[#857D78] dark:text-[#D1C9C3]"
						>Indexed Audio</span
					>
				</div>
				<div
					class="flex h-12 w-12 items-center justify-center rounded-xl bg-[#9A6548]/15 text-[#9A6548]"
				>
					<Clock class="h-6 w-6" />
				</div>
			</div>

			<div class="glass-card flex items-center justify-between rounded-2xl p-5 shadow-sm">
				<div>
					<span class="block text-xs font-semibold text-[#857D78] dark:text-[#D1C9C3]"
						>Catalog Storage</span
					>
					<span
						class="mt-1 block font-mono text-2xl font-extrabold text-[#2D2724] dark:text-[#F9F6F2]"
						>{formatBytes(stats.total_file_size)}</span
					>
					<span class="text-[11px] font-medium text-[#857D78] dark:text-[#D1C9C3]"
						>Local Metadata</span
					>
				</div>
				<div
					class="flex h-12 w-12 items-center justify-center rounded-xl bg-[#D8D66A]/30 text-[#5B534F] dark:text-[#E2E07E]"
				>
					<HardDrive class="h-6 w-6" />
				</div>
			</div>
		</div>
	{/if}

	<!-- Recently Added Tracks Grid -->
	{#if recentSongs.length > 0}
		<div class="space-y-4">
			<h2 class="flex items-center gap-2 text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">
				<Disc class="h-5 w-5 text-[#C97B45]" />
				Recently Added Tracks
			</h2>

			<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
				{#each recentSongs as song (song.id)}
					<div
						class="glass-card group flex items-center gap-3 rounded-2xl p-3 transition hover:shadow-md"
					>
						<div
							class="relative flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-[#E8E0D8] bg-[#F2ECE7] dark:border-white/10 dark:bg-white/10"
						>
							<img
								src={`${API_BASE_URL}/songs/${song.id}/cover?t=${song.sha256}`}
								alt={song.title || song.filename}
								class="h-full w-full object-cover"
								onerror={(e) => {
									const target = e.target as HTMLImageElement;
									target.style.display = 'none';
								}}
							/>
							<Music2 class="absolute -z-10 h-6 w-6 text-[#9A6548] dark:text-[#E58E53]" />
						</div>

						<div class="min-w-0 flex-1">
							<h3
								class="truncate text-sm font-bold text-[#2D2724] transition group-hover:text-[#C97B45] dark:text-[#F9F6F2]"
							>
								{song.title || song.filename}
							</h3>
							<p class="truncate text-xs text-[#857D78] dark:text-[#D1C9C3]">
								{song.artist || 'Unknown Artist'}
							</p>
						</div>

						<button
							class="hero-gradient btn btn-circle shrink-0 border-none text-white opacity-80 shadow-sm transition btn-xs group-hover:opacity-100"
							onclick={() => player.playTrack(song, recentSongs)}
							aria-label="Play track"
						>
							<Play class="ml-0.5 h-3 w-3 fill-current" />
						</button>
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Recent Scan Jobs Table -->
	<div class="glass-panel space-y-4 rounded-3xl p-6">
		<h2 class="text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">Recent Scan Jobs</h2>

		{#if recentJobs.length === 0}
			<p class="py-4 text-sm text-[#857D78] dark:text-[#D1C9C3]">No scan jobs executed yet.</p>
		{:else}
			<div class="overflow-x-auto">
				<table class="table w-full table-zebra text-xs">
					<thead>
						<tr class="text-[#857D78] dark:text-[#D1C9C3]">
							<th>ID</th>
							<th>Directory Path</th>
							<th>Status</th>
							<th>Progress</th>
							<th>Added / Updated</th>
						</tr>
					</thead>
					<tbody>
						{#each recentJobs as job (job.id)}
							<tr>
								<td class="font-mono font-bold text-[#2D2724] dark:text-[#F9F6F2]">#{job.id}</td>
								<td class="font-mono text-xs text-[#857D78] dark:text-[#D1C9C3]"
									>{job.directory_path}</td
								>
								<td>
									<span
										class={`badge badge-sm font-semibold ${
											job.status === 'completed'
												? 'text-white badge-success'
												: job.status === 'running'
													? 'text-white badge-info'
													: job.status === 'failed'
														? 'text-white badge-error'
														: 'badge-ghost'
										}`}
									>
										{job.status}
									</span>
								</td>
								<td class="font-mono text-[#2D2724] dark:text-[#F9F6F2]"
									>{job.scanned_files} / {job.total_files}</td
								>
								<td class="font-mono font-bold text-[#8E9570]"
									>+{job.added_count} / ~{job.updated_count}</td
								>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</div>

<!-- Modal Form Trigger Directory Scan -->
<dialog id="scan-modal" class="modal">
	<div class="glass-panel modal-box max-w-md rounded-3xl p-6">
		<h3 class="mb-4 text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">
			Start Directory Scan
		</h3>

		<div class="space-y-4">
			<div>
				<label for="directory-path" class="label">
					<span class="label-text text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]"
						>Audio Directory Path</span
					>
				</label>
				<input
					id="directory-path"
					type="text"
					bind:value={scanDirectory}
					placeholder="/music or C:\Users\..."
					class="input-bordered input w-full border-[#E8E0D8] bg-white/80 font-mono text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
				/>
				<span class="mt-1 block text-[11px] text-[#857D78] dark:text-[#D1C9C3]">
					If running in Docker Compose, use <code>/music</code>.
				</span>
			</div>

			<div class="form-control">
				<label class="label cursor-pointer justify-start gap-3">
					<input
						type="checkbox"
						bind:checked={performAudioAnalysis}
						class="checkbox checkbox-primary"
					/>
					<span class="label-text text-xs font-medium text-[#2D2724] dark:text-[#F9F6F2]"
						>Perform Librosa Audio Analysis (BPM & Key)</span
					>
				</label>
			</div>
		</div>

		<div class="modal-action mt-6">
			<form method="dialog">
				<button class="btn btn-ghost text-xs text-[#2D2724] btn-sm dark:text-[#F9F6F2]"
					>Cancel</button
				>
			</form>
			<button
				class="hero-gradient btn rounded-full border-none px-5 text-xs text-white shadow-md btn-sm"
				onclick={triggerScan}
				disabled={scanLoading}
			>
				{#if scanLoading}
					<span class="loading loading-xs loading-spinner"></span>
				{/if}
				Start Scan
			</button>
		</div>
	</div>
</dialog>
