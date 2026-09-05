<script lang="ts">
	import { onDestroy } from 'svelte';
	import {
		getDownloadPreview,
		startDownloadJob,
		getDownloadJobStatus,
		deleteDownloadJob,
		type DownloadPreviewResponse,
		type DownloadJobStatus
	} from '$lib/api/downloader';
	import { CloudDownload, RefreshCw, CheckCircle, Music, Sparkles } from '@lucide/svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let youtubeUrl = $state('');
	let selectedBitrate = $state(192);
	let autoImport = $state(true);

	let titleOverride = $state('');
	let artistOverride = $state('');
	let albumOverride = $state('');

	let isLoadingPreview = $state(false);
	let previewData = $state<DownloadPreviewResponse | null>(null);

	let currentJob = $state<DownloadJobStatus | null>(null);
	let pollInterval: ReturnType<typeof setInterval> | null = null;

	async function handleGetPreview() {
		if (!youtubeUrl.trim()) {
			toast.warning('Masukkan URL YouTube / YouTube Music terlebih dahulu.');
			return;
		}
		isLoadingPreview = true;
		previewData = null;

		try {
			const res = await getDownloadPreview(youtubeUrl.trim());
			previewData = res;
			titleOverride = res.title || '';
			artistOverride = res.artist || '';
			albumOverride = res.album || '';
		} catch (err) {
			toast.error((err as Error).message || 'Gagal mengambil metadata video.');
		} finally {
			isLoadingPreview = false;
		}
	}

	async function handleStartDownload() {
		if (!youtubeUrl.trim()) {
			toast.warning('Masukkan URL YouTube yang valid.');
			return;
		}

		try {
			const job = await startDownloadJob({
				url: youtubeUrl.trim(),
				bitrate: Number(selectedBitrate),
				title_override: titleOverride.trim() || undefined,
				artist_override: artistOverride.trim() || undefined,
				album_override: albumOverride.trim() || undefined,
				auto_import: autoImport
			});

			currentJob = job;
			toast.success('Download job berhasil dibuat.');
			startPolling(job.job_id);
		} catch (err) {
			toast.error((err as Error).message || 'Gagal memulai proses unduh.');
		}
	}

	function startPolling(jobId: string) {
		stopPolling();
		pollInterval = setInterval(async () => {
			try {
				const status = await getDownloadJobStatus(jobId);
				currentJob = status;

				if (status.status === 'done' || status.status === 'failed') {
					stopPolling();
					if (status.status === 'done') toast.success('Audio berhasil diunduh dan diproses.');
					else toast.error(status.error_message || 'Download audio gagal.');
				}
			} catch (err) {
				loggerError(err);
				stopPolling();
			}
		}, 1000);
	}

	function stopPolling() {
		if (pollInterval) {
			clearInterval(pollInterval);
			pollInterval = null;
		}
	}

	function loggerError(err: unknown) {
		console.error('Polling error:', err);
	}

	async function handleClearJob() {
		if (currentJob) {
			try {
				await deleteDownloadJob(currentJob.job_id);
				toast.success('Download job berhasil dihapus.');
			} catch (err) {
				toast.error((err as Error).message || 'Gagal menghapus download job.');
			}
		}
		stopPolling();
		currentJob = null;
	}

	onDestroy(() => {
		stopPolling();
	});
</script>

<div class="mx-auto max-w-4xl space-y-6">
	<!-- Page Header -->
	<div class="flex items-center justify-between">
		<div>
			<h1
				class="flex items-center gap-3 text-3xl font-extrabold tracking-tight text-[#2D2724] dark:text-[#F9F6F2]"
			>
				<CloudDownload class="h-8 w-8 text-[#C97B45]" />
				YT Music Downloader
			</h1>
			<p class="text-sm font-medium text-[#655E59] dark:text-[#D1C9C3]">
				Download audio YouTube Music dengan bitrate kustom, ID3 tagging, & auto-import ke pustaka
			</p>
		</div>
	</div>

	<!-- Form Card -->
	<div class="glass-panel space-y-6 rounded-3xl p-6">
		<h2 class="text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">
			YouTube Video URL & Konfigurasi
		</h2>

		<!-- Input URL & Bitrate -->
		<div class="grid grid-cols-1 gap-4 md:grid-cols-4">
			<div class="md:col-span-3">
				<label for="yt-url" class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">
					URL Video YouTube / YT Music
				</label>
				<div class="flex gap-2">
					<input
						id="yt-url"
						type="text"
						bind:value={youtubeUrl}
						placeholder="https://www.youtube.com/watch?v=... atau https://music.youtube.com/watch?v=..."
						class="input-bordered input w-full border-[#E8E0D8] bg-white/80 font-mono text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
					/>
					<button
						class="btn rounded-xl border-none bg-[#5B534F] text-xs font-bold text-white hover:bg-[#48423F]"
						onclick={handleGetPreview}
						disabled={isLoadingPreview}
					>
						{#if isLoadingPreview}
							<RefreshCw class="h-4 w-4 animate-spin" />
						{:else}
							<Sparkles class="h-4 w-4" />
						{/if}
						Preview
					</button>
				</div>
			</div>

			<div>
				<label
					for="bitrate-select"
					class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]"
				>
					Bitrate Output
				</label>
				<select
					id="bitrate-select"
					bind:value={selectedBitrate}
					class="select-bordered select w-full border-[#E8E0D8] bg-white/80 text-xs font-bold text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
				>
					<option value={128}>128 kbps</option>
					<option value={192}>192 kbps (Standard)</option>
					<option value={256}>256 kbps (High)</option>
					<option value={320}>320 kbps (Max)</option>
				</select>
			</div>
		</div>

		<!-- Preview Section -->
		{#if previewData}
			<div
				class="flex flex-col gap-4 rounded-2xl bg-[#F2ECE7] p-4 md:flex-row md:items-center dark:bg-white/10"
			>
				{#if previewData.thumbnail_url}
					<img
						src={previewData.thumbnail_url}
						alt="Thumbnail"
						class="h-24 w-32 shrink-0 rounded-xl object-cover shadow-md"
					/>
				{:else}
					<div
						class="flex h-24 w-32 shrink-0 items-center justify-center rounded-xl bg-[#5B534F]/20"
					>
						<Music class="h-8 w-8 text-[#5B534F]" />
					</div>
				{/if}
				<div class="flex-1 space-y-1">
					<h3 class="text-sm font-bold text-[#2D2724] dark:text-[#F9F6F2]">
						{previewData.title}
					</h3>
					<p class="text-xs font-medium text-[#655E59] dark:text-[#D1C9C3]">
						Artist: <span class="font-bold">{previewData.artist}</span>
						{#if previewData.album}
							• Album: {previewData.album}{/if}
					</p>
					{#if previewData.source_bitrate_estimate}
						<span
							class="inline-block rounded-md bg-[#8E9570]/30 px-2 py-0.5 font-mono text-[10px] font-bold text-[#484E31] dark:text-[#D9DEC3]"
						>
							Source ABR Est: ~{previewData.source_bitrate_estimate} kbps
						</span>
					{/if}
				</div>
			</div>
		{/if}

		<!-- Optional Metadata Override Fields -->
		<div class="grid grid-cols-1 gap-4 md:grid-cols-3">
			<div>
				<label
					for="override-title"
					class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]"
				>
					Title (Override)
				</label>
				<input
					id="override-title"
					type="text"
					bind:value={titleOverride}
					placeholder="Judul lagu"
					class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
				/>
			</div>

			<div>
				<label
					for="override-artist"
					class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]"
				>
					Artist (Override)
				</label>
				<input
					id="override-artist"
					type="text"
					bind:value={artistOverride}
					placeholder="Nama penyanyi / artist"
					class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
				/>
			</div>

			<div>
				<label
					for="override-album"
					class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]"
				>
					Album (Override)
				</label>
				<input
					id="override-album"
					type="text"
					bind:value={albumOverride}
					placeholder="Nama album"
					class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
				/>
			</div>
		</div>

		<!-- Auto-Import Checkbox -->
		<div class="flex items-center gap-2">
			<input
				id="auto-import-check"
				type="checkbox"
				bind:checked={autoImport}
				class="checkbox checkbox-sm checkbox-primary"
			/>
			<label for="auto-import-check" class="text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">
				Otomatis import hasil unduhan ke Pustaka Musik (/music) & indeks ke TuneVault DB
			</label>
		</div>

		<!-- Action Buttons -->
		<div class="pt-2">
			<button
				class="hero-gradient btn rounded-full border-none px-6 text-xs text-white shadow-md"
				onclick={handleStartDownload}
				disabled={currentJob?.status === 'downloading' ||
					currentJob?.status === 'converting' ||
					currentJob?.status === 'tagging'}
			>
				<CloudDownload class="h-4 w-4" />
				Mulai Download Audio
			</button>
		</div>
	</div>

	<!-- Live Job Status Card -->
	{#if currentJob}
		<div class="glass-panel space-y-4 rounded-3xl p-6">
			<div class="flex items-center justify-between">
				<h2 class="text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">Progres Unduhan</h2>
				<button class="btn btn-ghost text-[#655E59] btn-xs" onclick={handleClearJob}>
					Clear Status
				</button>
			</div>

			<div class="space-y-3">
				<div class="flex items-center justify-between text-xs font-bold">
					<span class="tracking-wider text-[#655E59] uppercase dark:text-[#D1C9C3]">
						Status: <span class="font-extrabold text-[#C97B45]">{currentJob.status}</span>
					</span>
					<span class="font-mono text-[#2D2724] dark:text-[#F9F6F2]">
						{Math.round(currentJob.progress_percent)}%
					</span>
				</div>

				<progress
					class="progress w-full progress-primary"
					value={currentJob.progress_percent}
					max="100"
				></progress>

				{#if currentJob.status === 'done'}
					<div
						class="flex items-center gap-3 rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-xs font-bold text-emerald-800 dark:text-emerald-300"
					>
						<CheckCircle class="h-5 w-5 shrink-0" />
						<div>
							<p>Audio berhasil diunduh, di-encode ke {currentJob.bitrate}kbps, & di-tag ID3!</p>
							{#if currentJob.imported_song_id}
								<p class="mt-1 font-normal text-emerald-700 dark:text-emerald-400">
									Lagu telah otomatis di-import ke pustaka TuneVault (ID #{currentJob.imported_song_id}).
								</p>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
