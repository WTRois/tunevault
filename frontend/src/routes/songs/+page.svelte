<script lang="ts">
	/* eslint-disable svelte/prefer-svelte-reactivity, @typescript-eslint/no-unused-vars */
	import { onMount } from 'svelte';
	import { api, API_BASE_URL } from '$lib/api/client';
	import { getFileAnalysis, startAnalysis, getJob, type AudioAnalysis } from '$lib/api/analysis';
	import { player } from '$lib/stores/player.svelte';
	import { editModal } from '$lib/stores/editModal.svelte';
	import { toast } from '$lib/stores/toast.svelte';
	import { formatDuration, formatBytes } from '$lib/utils/os';
	import { Eye, Edit3, Music2, Pencil, Gauge } from '@lucide/svelte';

	interface Song {
		id: number;
		filename: string;
		filepath: string;
		sha256: string;
		title?: string;
		artist?: string;
		album?: string;
		album_artist?: string;
		composer?: string;
		genre?: string;
		year?: number;
		track_number?: number;
		disc_number?: number;
		duration?: number;
		bitrate?: number;
		codec?: string;
		sample_rate?: number;
		channels?: number;
		file_size?: number;
		bpm?: number;
		musical_key?: string;
		lyrics?: string;
		has_cover: boolean;
	}

	interface PaginatedSongs {
		items: Song[];
		total: number;
		page: number;
		limit: number;
		pages: number;
	}

	let songs = $state<Song[]>([]);
	let totalSongs = $state(0);
	let page = $state(1);
	let limit = $state(20);
	let totalPages = $state(1);
	let loading = $state(true);

	// Filters & Sorting
	let search = $state('');
	let selectedGenre = $state('');
	let sortBy = $state('id');
	let order = $state<'asc' | 'desc'>('asc');

	// Detail & Edit Modal
	let selectedSong = $state<Song | null>(null);
	let activeTab = $state<'overview' | 'edit' | 'technical'>('overview');
	let editLoading = $state(false);

	// Technical analysis tab (TV2-031)
	let analysis = $state<AudioAnalysis | null>(null);
	let analysisLoading = $state(false);
	let analyzing = $state(false);

	// Edit Form State
	let editTitle = $state('');
	let editArtist = $state('');
	let editAlbum = $state('');
	let editAlbumArtist = $state('');
	let editGenre = $state('');
	let editYear = $state<number | undefined>(undefined);
	let editTrackNumber = $state<number | undefined>(undefined);
	let editDiscNumber = $state<number | undefined>(undefined);
	let editComposer = $state('');
	let editLyrics = $state('');

	// Cover Image Upload State
	let coverFile = $state<File | null>(null);
	let coverPreview = $state<string | null>(null);
	let isDragOver = $state(false);

	// Artwork candidates from Cover Art Archive (TV2-023)
	interface ArtworkCandidate {
		id: number;
		local_path: string;
		type: string;
		width: number | null;
		height: number | null;
		quality_score: number | null;
		is_embedded: boolean;
	}
	let artworkCandidates = $state<ArtworkCandidate[]>([]);
	let artworkSearching = $state(false);
	let applyingArtworkId = $state<number | null>(null);

	onMount(() => {
		loadSongs();
	});

	async function loadSongs() {
		loading = true;
		try {
			const queryParams = new URLSearchParams({
				page: page.toString(),
				limit: limit.toString(),
				sort_by: sortBy,
				order: order
			});
			if (search) queryParams.set('search', search);
			if (selectedGenre) queryParams.set('genre', selectedGenre);

			const res = await api.get<PaginatedSongs>(`/songs?${queryParams.toString()}`);
			songs = res.items;
			totalSongs = res.total;
			totalPages = res.pages;
		} catch (err) {
			console.error('Failed to load songs:', err);
		} finally {
			loading = false;
		}
	}

	function handleSearch() {
		page = 1;
		loadSongs();
	}

	function handleSort(column: string) {
		if (sortBy === column) {
			order = order === 'asc' ? 'desc' : 'asc';
		} else {
			sortBy = column;
			order = 'asc';
		}
		loadSongs();
	}

	function openDetail(song: Song, tab: 'overview' | 'edit' | 'technical' = 'overview') {
		selectedSong = song;
		activeTab = tab;
		const modal = document.getElementById('song-detail-modal') as HTMLDialogElement;
		modal?.showModal();
		if (tab === 'technical') {
			void loadAnalysis();
		}
	}

	async function loadAnalysis() {
		if (!selectedSong) return;
		analysisLoading = true;
		try {
			analysis = await getFileAnalysis(selectedSong.id);
		} catch (err) {
			toast.error((err as Error).message || 'Failed to load analysis');
		} finally {
			analysisLoading = false;
		}
	}

	async function runAnalysis() {
		if (!selectedSong) return;
		analyzing = true;
		try {
			const res = await startAnalysis(selectedSong.id);
			await pollAnalysisJob(res.job_id);
		} catch (err) {
			toast.error((err as Error).message || 'Failed to start analysis');
			analyzing = false;
		}
	}

	async function pollAnalysisJob(jobId: number) {
		try {
			const job = await getJob(jobId);
			if (job.status === 'completed') {
				analyzing = false;
				toast.success('Analysis complete');
				await loadAnalysis();
				return;
			}
			if (job.status === 'failed') {
				analyzing = false;
				toast.error(job.error_message || 'Analysis failed');
				return;
			}
			setTimeout(() => void pollAnalysisJob(jobId), 1500);
		} catch (err) {
			analyzing = false;
			toast.error((err as Error).message || 'Lost track of analysis job');
		}
	}

	function fmtDb(value: number | null | undefined, unit = 'dBFS'): string {
		return value === null || value === undefined ? '—' : `${value.toFixed(1)} ${unit}`;
	}

	function fmtHz(value: number | null | undefined): string {
		return value === null || value === undefined ? '—' : `${(value / 1000).toFixed(1)} kHz`;
	}

	function fmtKbps(value: number | null | undefined): string {
		return value === null || value === undefined ? '—' : `${Math.round(value / 1000)} kbps`;
	}

	function playSong(song: Song) {
		if (player.currentTrack?.id === song.id && !player.isPlaying) {
			player.togglePlay();
		} else if (player.currentTrack?.id !== song.id) {
			player.playTrack(song, songs);
		}
	}

	async function saveMetadata() {
		if (!selectedSong) return;
		editLoading = true;

		try {
			// 1. Update Text Metadata
			const updated = await api.put<Song>(`/songs/${selectedSong.id}/metadata`, {
				title: editTitle,
				artist: editArtist,
				album: editAlbum,
				album_artist: editAlbumArtist,
				genre: editGenre,
				year: editYear,
				track_number: editTrackNumber,
				disc_number: editDiscNumber,
				composer: editComposer,
				lyrics: editLyrics
			});

			// 2. Upload Cover Image if selected
			if (coverFile) {
				const formData = new FormData();
				formData.append('file', coverFile);
				const res = await fetch(`${API_BASE_URL}/songs/${selectedSong.id}/cover`, {
					method: 'POST',
					body: formData
				});
				if (!res.ok) throw new Error('Failed to upload cover image');
			}

			selectedSong = updated;
			toast.success('Metadata berhasil disimpan ke file audio dan katalog.');
			await loadSongs();
		} catch (err) {
			toast.error((err as Error).message || 'Failed to update metadata');
		} finally {
			editLoading = false;
		}
	}

	function handleCoverDrop(e: DragEvent) {
		e.preventDefault();
		isDragOver = false;
		if (e.dataTransfer?.files && e.dataTransfer.files[0]) {
			setCoverFile(e.dataTransfer.files[0]);
		}
	}

	function handleCoverSelect(e: Event) {
		const target = e.target as HTMLInputElement;
		if (target.files && target.files[0]) {
			setCoverFile(target.files[0]);
		}
	}

	function setCoverFile(file: File) {
		if (!file.type.startsWith('image/')) {
			toast.warning('Pilih file gambar yang valid (.jpg, .png, .webp).');
			return;
		}
		coverFile = file;
		coverPreview = URL.createObjectURL(file);
	}

	async function removeCover() {
		if (!selectedSong) return;
		if (!confirm('Remove embedded cover art from audio file?')) return;
		try {
			await api.delete(`/songs/${selectedSong.id}/cover`);
			coverFile = null;
			coverPreview = null;
			selectedSong.has_cover = false;
			toast.success('Cover art berhasil dihapus.');
			await loadSongs();
		} catch (err) {
			toast.error((err as Error).message || 'Failed to remove cover art');
		}
	}

	async function searchArtwork() {
		if (!selectedSong) return;
		artworkSearching = true;
		try {
			const res = await api.post<ArtworkCandidate[]>(`/files/${selectedSong.id}/artwork/search`);
			artworkCandidates = res;
			if (res.length === 0) {
				toast.info('Tidak ada kandidat artwork dari Cover Art Archive.');
			}
		} catch (err) {
			toast.error((err as Error).message || 'Artwork search gagal');
		} finally {
			artworkSearching = false;
		}
	}

	async function applyArtwork(artworkId: number) {
		if (!selectedSong) return;
		applyingArtworkId = artworkId;
		try {
			const res = await api.post<{ sha256: string }>(`/files/${selectedSong.id}/artwork/apply`, {
				artwork_id: artworkId
			});
			selectedSong.has_cover = true;
			selectedSong.sha256 = res.sha256;
			coverPreview = null;
			artworkCandidates = [];
			toast.success('Artwork berhasil di-embed ke file audio.');
			await loadSongs();
		} catch (err) {
			toast.error((err as Error).message || 'Gagal menerapkan artwork');
		} finally {
			applyingArtworkId = null;
		}
	}

	async function deleteSong(songId: number) {
		if (!confirm(`Are you sure you want to delete song #${songId} from index?`)) return;
		try {
			await api.delete(`/songs/${songId}`);
			toast.success('Song record berhasil dihapus dari katalog.');
			const modal = document.getElementById('song-detail-modal') as HTMLDialogElement;
			modal?.close();
			selectedSong = null;
			await loadSongs();
		} catch (err) {
			toast.error((err as Error).message || 'Failed to delete song');
		}
	}
</script>

<div class="space-y-6">
	<!-- Page Header -->
	<div class="flex flex-col justify-between gap-4 md:flex-row md:items-center">
		<div>
			<h1 class="text-3xl font-extrabold tracking-tight text-[#2D2724] dark:text-[#F9F6F2]">
				Songs Catalog
			</h1>
			<p class="text-sm font-medium text-[#655E59] dark:text-[#D1C9C3]">
				Showing {totalSongs} indexed tracks
			</p>
		</div>

		<!-- Search Bar & Filters -->
		<div class="flex flex-wrap items-center gap-2">
			<input
				type="text"
				placeholder="Search title, artist, album..."
				bind:value={search}
				oninput={handleSearch}
				class="input w-64 border-[#E8E0D8] bg-white/80 text-[#2D2724] input-sm dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
			/>
		</div>
	</div>

	<!-- Songs DataTable -->
	<div
		class="glass-panel overflow-hidden rounded-3xl border border-[#E8E0D8] shadow-lg dark:border-white/10"
	>
		<div class="overflow-x-auto">
			<table class="table w-full text-xs">
				<thead>
					<tr
						class="border-b border-[#E8E0D8] bg-[#EBE4DC] text-[#4A433F] dark:border-white/10 dark:bg-[#15110F] dark:text-[#D1C9C3]"
					>
						<th>Cover</th>
						<th class="cursor-pointer font-bold" onclick={() => handleSort('title')}>Title</th>
						<th class="cursor-pointer font-bold" onclick={() => handleSort('artist')}>Artist</th>
						<th class="cursor-pointer font-bold" onclick={() => handleSort('album')}>Album</th>
						<th class="cursor-pointer font-bold" onclick={() => handleSort('genre')}>Genre</th>
						<th class="cursor-pointer font-bold" onclick={() => handleSort('duration')}>Duration</th
						>
						<th class="cursor-pointer font-bold" onclick={() => handleSort('bpm')}>BPM</th>
						<th class="font-bold">Key</th>
						<th class="font-bold">Actions</th>
					</tr>
				</thead>

				<tbody>
					{#if loading}
						{#each Array.from({ length: 5 }) as _, idx (idx)}
							<tr>
								<td colspan="9"><div class="h-8 w-full skeleton rounded-xl"></div></td>
							</tr>
						{/each}
					{:else if songs.length === 0}
						<tr>
							<td colspan="9" class="py-8 text-center text-[#857D78] dark:text-[#D1C9C3]">
								No songs found matching your filter criteria.
							</td>
						</tr>
					{:else}
						{#each songs as song (song.id)}
							<tr
								class="cursor-pointer border-b border-[#E8E0D8]/40 transition-all duration-200 ease-in-out odd:bg-[#F9F6F2] even:bg-[#F2ECE7] hover:bg-[#C97B45]/15 hover:shadow-sm dark:border-white/5 dark:odd:bg-[#1E1917] dark:even:bg-[#25201D] dark:hover:bg-[#C97B45]/25"
								onclick={() => playSong(song)}
							>
								<td>
									<div
										class="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-[#E8E0D8] bg-[#F2ECE7] dark:border-white/10 dark:bg-white/10"
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
										<Music2 class="absolute -z-10 h-5 w-5 text-[#9A6548] dark:text-[#E58E53]" />
									</div>
								</td>
								<td class="font-bold text-[#2D2724] dark:text-[#F9F6F2]"
									>{song.title || song.filename}</td
								>
								<td class="font-medium text-[#655E59] dark:text-[#D1C9C3]"
									>{song.artist || 'Unknown Artist'}</td
								>
								<td class="font-medium text-[#655E59] dark:text-[#D1C9C3]"
									>{song.album || 'Unknown Album'}</td
								>
								<td>
									{#if song.genre}
										<span
											class="badge border-none bg-[#C97B45]/15 badge-sm font-semibold text-[#6E4330] dark:bg-[#C97B45]/30 dark:text-[#F3D9C9]"
											>{song.genre}</span
										>
									{:else}
										<span class="text-xs font-semibold text-[#857D78] dark:text-[#D1C9C3]/50"
											>-</span
										>
									{/if}
								</td>
								<td class="font-mono text-xs text-[#2D2724] dark:text-[#F9F6F2]"
									>{formatDuration(song.duration)}</td
								>
								<td class="font-mono text-xs text-[#2D2724] dark:text-[#F9F6F2]"
									>{song.bpm || '-'}</td
								>
								<td class="font-mono text-xs text-[#2D2724] dark:text-[#F9F6F2]"
									>{song.musical_key || '-'}</td
								>
								<td>
									<div class="flex items-center gap-1">
										<div class="tooltip tooltip-top" data-tip="View details">
											<button
												class="btn btn-square btn-ghost text-[#6E4330] btn-xs dark:text-[#E58E53]"
												onclick={(event) => {
													event.stopPropagation();
													openDetail(song);
												}}
												aria-label={`View details for ${song.title || song.filename}`}
												title="View details"
											>
												<Eye class="h-4 w-4" />
											</button>
										</div>
										<div class="tooltip tooltip-top" data-tip="Edit metadata">
											<button
												class="btn btn-square btn-ghost text-[#857D78] btn-xs dark:text-[#D1C9C3]"
												onclick={(event) => {
													event.stopPropagation();
													openDetail(song, 'edit');
												}}
												aria-label={`Edit metadata for ${song.title || song.filename}`}
												title="Edit metadata"
											>
												<Pencil class="h-4 w-4" />
											</button>
										</div>
									</div>
								</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
		</div>

		<!-- Pagination Footer -->
		<div
			class="card-body flex flex-row items-center justify-between border-t border-[#E8E0D8] py-3 dark:border-white/10"
		>
			<span class="text-xs font-medium text-[#655E59] dark:text-[#D1C9C3]">
				Page {page} of {totalPages}
			</span>
			<div class="join">
				<button
					class="btn join-item border-[#E8E0D8] bg-[#F2ECE7] text-[#2D2724] transition-all duration-200 ease-in-out btn-xs hover:bg-[#C97B45] hover:text-white dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2] dark:hover:bg-[#C97B45]"
					disabled={page <= 1}
					onclick={() => {
						page--;
						loadSongs();
					}}
				>
					« Prev
				</button>
				<button
					class="btn join-item border-[#E8E0D8] bg-[#F2ECE7] text-[#2D2724] transition-all duration-200 ease-in-out btn-xs hover:bg-[#C97B45] hover:text-white dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2] dark:hover:bg-[#C97B45]"
					disabled={page >= totalPages}
					onclick={() => {
						page++;
						loadSongs();
					}}
				>
					Next »
				</button>
			</div>
		</div>
	</div>
</div>

<!-- Song Detail & Edit Drawer / Modal -->
<dialog id="song-detail-modal" class="modal">
	<div
		class="glass-panel relative modal-box w-11/12 max-w-3xl overflow-hidden rounded-3xl p-6 text-[#2D2724] dark:text-[#F9F6F2]"
	>
		<form method="dialog">
			<button
				class="btn absolute top-3 right-3 btn-circle btn-ghost text-[#857D78] btn-sm dark:text-[#F9F6F2]"
				aria-label="Close modal">✕</button
			>
		</form>

		{#if selectedSong}
			<!-- Tabs Navigation -->
			<div class="tabs-boxed tabs mb-4 w-fit bg-[#F2ECE7] dark:bg-white/10">
				<button
					class={`tab text-xs font-semibold ${activeTab === 'overview' ? 'tab-active bg-[#C97B45] font-bold text-white' : 'text-[#857D78] dark:text-[#D1C9C3]'}`}
					onclick={() => (activeTab = 'overview')}
				>
					Overview
				</button>
				<button
					class={`tab text-xs font-semibold ${
						activeTab === 'technical'
							? 'tab-active bg-[#C97B45] font-bold text-white'
							: 'text-[#857D78] dark:text-[#D1C9C3]'
					}`}
					onclick={() => {
						activeTab = 'technical';
						void loadAnalysis();
					}}
				>
					<Gauge class="h-3.5 w-3.5" /> Technical
				</button>
				<button
					class={`tab text-xs font-semibold ${activeTab === 'edit' ? 'tab-active bg-[#C97B45] font-bold text-white' : 'text-[#857D78] dark:text-[#D1C9C3]'}`}
					onclick={() => (activeTab = 'edit')}
				>
					<Edit3 class="h-3.5 w-3.5" /> Edit Metadata &amp; Cover
				</button>
			</div>

			{#if activeTab === 'overview'}
				<!-- OVERVIEW TAB -->
				<div class="flex flex-col items-start gap-6 md:flex-row">
					<!-- Cover Art Preview -->
					<div class="mx-auto h-40 w-40 shrink-0 md:mx-0 md:h-44 md:w-44">
						<img
							src={`${API_BASE_URL}/songs/${selectedSong.id}/cover?t=${selectedSong.sha256}`}
							alt={selectedSong.title || 'Cover'}
							class="h-full w-full rounded-2xl border border-[#E8E0D8] object-cover shadow-lg dark:border-white/10"
						/>
					</div>

					<!-- Song Header Info -->
					<div class="min-w-0 flex-1 space-y-3">
						<div>
							<h3
								class="text-xl font-extrabold break-words text-[#2D2724] md:text-2xl dark:text-[#F9F6F2]"
							>
								{selectedSong.title || selectedSong.filename}
							</h3>
							<p class="text-base font-bold text-[#C97B45] dark:text-[#E58E53]">
								{selectedSong.artist || 'Unknown Artist'}
							</p>
							<p class="text-xs text-[#857D78] dark:text-[#D1C9C3]">
								{selectedSong.album || 'Unknown Album'}
								{#if selectedSong.year}({selectedSong.year}){/if}
							</p>
						</div>

						<div class="flex flex-wrap gap-2">
							{#if selectedSong.genre}
								<span
									class="badge border-none bg-[#8E9570]/20 text-xs font-semibold text-[#2D2724] dark:text-[#F9F6F2]"
									>{selectedSong.genre}</span
								>
							{/if}
							{#if selectedSong.codec}
								<span class="badge bg-[#5B534F] font-mono text-xs text-white"
									>{selectedSong.codec.toUpperCase()}</span
								>
							{/if}
							{#if selectedSong.musical_key}
								<span
									class="badge border-none bg-[#D8D66A]/30 font-mono text-xs font-semibold text-[#2D2724] dark:text-[#F9F6F2]"
									>Key: {selectedSong.musical_key}</span
								>
							{/if}
							{#if selectedSong.bpm}
								<span
									class="badge border-none bg-[#C97B45]/20 font-mono text-xs font-semibold text-[#C97B45] dark:text-[#E58E53]"
									>{selectedSong.bpm} BPM</span
								>
							{/if}
						</div>
					</div>
				</div>

				<!-- Detailed Metadata Grid -->
				<div
					class="mt-6 grid grid-cols-2 gap-3 rounded-2xl border border-[#E8E0D8] bg-[#F2ECE7]/80 p-4 font-mono text-xs sm:grid-cols-4 dark:border-white/10 dark:bg-white/10"
				>
					<div>
						<span class="block text-[#857D78] dark:text-[#D1C9C3]">Duration</span>
						<span class="text-sm font-extrabold text-[#2D2724] dark:text-[#F9F6F2]"
							>{formatDuration(selectedSong.duration)}</span
						>
					</div>
					<div>
						<span class="block text-[#857D78] dark:text-[#D1C9C3]">Bitrate</span>
						<span class="text-sm font-extrabold text-[#2D2724] dark:text-[#F9F6F2]"
							>{selectedSong.bitrate
								? `${Math.round(selectedSong.bitrate / 1000)} kbps`
								: 'N/A'}</span
						>
					</div>
					<div>
						<span class="block text-[#857D78] dark:text-[#D1C9C3]">Sample Rate</span>
						<span class="text-sm font-extrabold text-[#2D2724] dark:text-[#F9F6F2]"
							>{selectedSong.sample_rate ? `${selectedSong.sample_rate} Hz` : 'N/A'}</span
						>
					</div>
					<div>
						<span class="block text-[#857D78] dark:text-[#D1C9C3]">File Size</span>
						<span class="text-sm font-extrabold text-[#2D2724] dark:text-[#F9F6F2]"
							>{formatBytes(selectedSong.file_size)}</span
						>
					</div>
				</div>

				<!-- File system paths & hashes -->
				<div
					class="mt-4 space-y-2 rounded-2xl border border-[#E8E0D8] bg-[#F2ECE7]/50 p-3 font-mono text-xs text-[#2D2724] dark:border-white/10 dark:bg-black/20 dark:text-[#F9F6F2]"
				>
					<div class="break-all">
						<span class="font-bold text-[#857D78] dark:text-[#D1C9C3]">Filepath:</span>
						{selectedSong.filepath}
					</div>
					<div class="break-all">
						<span class="font-bold text-[#857D78] dark:text-[#D1C9C3]">SHA-256:</span>
						{selectedSong.sha256}
					</div>
				</div>

				<!-- Lyrics Section if present -->
				{#if selectedSong.lyrics}
					<div class="mt-4 border-t border-[#E8E0D8] pt-4 dark:border-white/10">
						<h4 class="mb-2 text-sm font-bold text-[#2D2724] dark:text-[#F9F6F2]">Lyrics</h4>
						<pre
							class="max-h-40 overflow-y-auto rounded-xl bg-[#F2ECE7] p-3 text-xs whitespace-pre-wrap text-[#2D2724] dark:bg-white/10 dark:text-[#F9F6F2]">{selectedSong.lyrics}</pre>
					</div>
				{/if}

				<!-- Actions Bar -->
				<div
					class="modal-action mt-6 flex items-center justify-between border-t border-[#E8E0D8] pt-4 dark:border-white/10"
				>
					<div class="flex items-center gap-2">
						<button
							class="hero-gradient btn border-none text-white btn-sm"
							onclick={() => (activeTab = 'edit')}
						>
							<Edit3 class="h-3.5 w-3.5" /> Edit Metadata
						</button>
						<button
							class="btn btn-outline btn-error btn-sm"
							onclick={() => deleteSong(selectedSong!.id)}
						>
							Delete Record
						</button>
					</div>
					<form method="dialog">
						<button class="btn btn-ghost text-[#2D2724] btn-sm dark:text-[#F9F6F2]">Close</button>
					</form>
				</div>
			{:else if activeTab === 'technical'}
				<!-- TECHNICAL / ANALYSIS TAB (TV2-031, blueprint §12) -->
				<div class="space-y-4">
					<div class="flex items-center justify-between">
						<h4 class="text-sm font-bold text-[#2D2724] dark:text-[#F9F6F2]">
							Technical & Analysis
						</h4>
						<button
							class="hero-gradient btn border-none text-white btn-sm"
							disabled={analyzing}
							onclick={() => runAnalysis()}
						>
							{analyzing ? 'Analyzing…' : analysis?.analyzed ? 'Re-analyze' : 'Run Analysis'}
						</button>
					</div>

					{#if analysisLoading}
						<p class="text-sm text-[#857D78] dark:text-[#D1C9C3]">Loading analysis…</p>
					{:else if !analysis || !analysis.analyzed}
						<p class="text-sm text-[#857D78] dark:text-[#D1C9C3]">
							No analysis yet — run the analyzer to measure loudness, spectral and technical
							details.
						</p>
					{:else if analysis}
						<!-- TECHNICAL + LOUDNESS -->
						<div class="grid gap-4 md:grid-cols-2">
							<div class="rounded-2xl border border-[#E8E0D8] p-4 dark:border-white/10">
								<h5 class="mb-2 text-xs font-bold text-[#857D78] uppercase dark:text-[#D1C9C3]">
									Technical
								</h5>
								<dl class="space-y-1 text-sm">
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Codec / Container</dt>
										<dd class="font-medium text-[#2D2724] capitalize dark:text-[#F9F6F2]">
											{analysis.technical.codec ?? '—'} / {analysis.technical.container ?? '—'}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Format</dt>
										<dd>
											{#if analysis.technical.lossless === true}
												<span class="badge text-xs badge-sm badge-success">Lossless</span>
											{:else if analysis.technical.lossless === false}
												<span class="badge badge-ghost text-xs badge-sm">Lossy</span>
											{:else}
												<span class="text-[#857D78]">Unknown</span>
											{/if}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Sample Rate</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{analysis.technical.sample_rate
												? `${(analysis.technical.sample_rate / 1000).toFixed(1)} kHz`
												: '—'}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Bit Depth</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{analysis.technical.bit_depth ? `${analysis.technical.bit_depth}-bit` : '—'}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Channels</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{analysis.technical.channels ?? '—'}
											{analysis.technical.channel_layout
												? `(${analysis.technical.channel_layout})`
												: ''}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Bitrate</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{fmtKbps(analysis.technical.bitrate)}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Duration</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{analysis.technical.duration_ms
												? formatDuration(analysis.technical.duration_ms / 1000)
												: '—'}
										</dd>
									</div>
								</dl>
							</div>

							<div class="rounded-2xl border border-[#E8E0D8] p-4 dark:border-white/10">
								<h5 class="mb-2 text-xs font-bold text-[#857D78] uppercase dark:text-[#D1C9C3]">
									Loudness
								</h5>
								<dl class="space-y-1 text-sm">
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Integrated</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{fmtDb(analysis.features?.integrated_lufs, 'LUFS')}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">True Peak</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{fmtDb(analysis.features?.true_peak_db)}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">ReplayGain Track</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{fmtDb(analysis.features?.replaygain_track_db, 'dB')}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Dynamic Range</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{fmtDb(analysis.features?.dynamic_range, 'LU')}
										</dd>
									</div>
								</dl>
							</div>

							<!-- SPECTRAL + MUSICALITY -->
							<div class="rounded-2xl border border-[#E8E0D8] p-4 dark:border-white/10">
								<h5 class="mb-2 text-xs font-bold text-[#857D78] uppercase dark:text-[#D1C9C3]">
									Spectral
								</h5>
								<dl class="space-y-1 text-sm">
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Centroid</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{fmtHz(analysis.features?.spectral_centroid)}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Frequency Ceiling</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{fmtHz(analysis.features?.frequency_ceiling_hz)}
										</dd>
									</div>
								</dl>
								{#if analysis.upsample}
									<div class="mt-3">
										{#if analysis.upsample.status === 'possible_upsample'}
											<span class="badge text-xs badge-sm badge-warning">
												Possible Upsample ({analysis.upsample.confidence})
											</span>
											<span class="text-xs text-[#857D78] dark:text-[#D1C9C3]">
												— warning only, never a verdict
											</span>
										{:else if analysis.upsample.status === 'normal'}
											<span class="badge text-xs badge-sm badge-success">Normal</span>
										{:else}
											<span class="badge badge-ghost text-xs badge-sm">Insufficient data</span>
										{/if}
									</div>
								{/if}
							</div>

							<div class="rounded-2xl border border-[#E8E0D8] p-4 dark:border-white/10">
								<h5 class="mb-2 text-xs font-bold text-[#857D78] uppercase dark:text-[#D1C9C3]">
									Musicality
								</h5>
								<dl class="space-y-1 text-sm">
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">BPM</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{analysis.features?.bpm ?? '—'}
										</dd>
									</div>
									<div class="flex justify-between gap-2">
										<dt class="text-[#857D78] dark:text-[#D1C9C3]">Key</dt>
										<dd class="font-medium text-[#2D2724] dark:text-[#F9F6F2]">
											{analysis.features?.musical_key ?? '—'}
										</dd>
									</div>
								</dl>
							</div>
						</div>

						<p class="text-xs text-[#857D78] dark:text-[#D1C9C3]">
							Analyzed {analysis.analyzed_at ? new Date(analysis.analyzed_at).toLocaleString() : ''} ·
							engine {analysis.analysis_version ?? '—'}
						</p>
					{/if}
				</div>
			{:else}
				<!-- EDIT METADATA TAB -->
				<div class="space-y-4">
					<!-- Cover Art Drag-and-Drop Uploader -->
					<div class="flex flex-col items-center gap-4 sm:flex-row">
						<div class="h-32 w-32 shrink-0">
							<img
								src={coverPreview ||
									`${API_BASE_URL}/songs/${selectedSong.id}/cover?t=${selectedSong.sha256}`}
								alt="Cover Preview"
								class="h-full w-full rounded-2xl border border-[#E8E0D8] object-cover shadow dark:border-white/10"
							/>
						</div>

						<div class="w-full flex-1 space-y-2">
							<label
								for="cover-file-input"
								class={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-4 text-center text-xs transition ${
									isDragOver
										? 'border-[#C97B45] bg-[#C97B45]/10'
										: 'border-[#E8E0D8] hover:border-[#C97B45] dark:border-white/20'
								}`}
								ondragover={(e) => {
									e.preventDefault();
									isDragOver = true;
								}}
								ondragleave={() => (isDragOver = false)}
								ondrop={handleCoverDrop}
							>
								<span class="font-bold text-[#2D2724] dark:text-[#F9F6F2]"
									>Drag & Drop new Cover Art image here</span
								>
								<span class="text-[#857D78] dark:text-[#D1C9C3]"
									>or click to browse (.jpg, .png, .webp)</span
								>
								<input
									id="cover-file-input"
									type="file"
									accept="image/*"
									onchange={handleCoverSelect}
									class="hidden"
								/>
							</label>

							{#if selectedSong.has_cover || coverPreview}
								<button class="btn btn-ghost text-error btn-xs" onclick={removeCover}>
									Remove Cover Art
								</button>
							{/if}

							<!-- Cover Art Archive candidates (TV2-023, §11) -->
							<button
								class="btn mt-1 btn-outline btn-xs"
								disabled={artworkSearching}
								onclick={searchArtwork}
							>
								{artworkSearching ? 'Searching…' : 'Cari Artwork (Cover Art Archive)'}
							</button>

							{#if artworkCandidates.length > 0}
								<div class="mt-2 space-y-2">
									{#each artworkCandidates as candidate (candidate.id)}
										<div
											class="flex items-center gap-3 rounded-xl border border-[#E8E0D8] p-2 dark:border-white/10"
										>
											<img
												src={`${API_BASE_URL}/artworks/${candidate.id}/image`}
												alt="Candidate artwork"
												class="h-14 w-14 rounded-lg object-cover"
											/>
											<div class="flex-1 text-xs">
												<div class="font-bold text-[#2D2724] capitalize dark:text-[#F9F6F2]">
													{candidate.type}
												</div>
												<div class="text-[#857D78] dark:text-[#D1C9C3]">
													{candidate.width}×{candidate.height} · score {candidate.quality_score}
												</div>
											</div>
											<button
												class="btn btn-primary btn-xs"
												disabled={applyingArtworkId !== null}
												onclick={() => applyArtwork(candidate.id)}
											>
												{applyingArtworkId === candidate.id ? 'Embedding…' : 'Use This'}
											</button>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					</div>

					<!-- Form Metadata Text Inputs -->
					<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
						<div>
							<label
								for="edit-title"
								class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">Title</label
							>
							<input
								id="edit-title"
								type="text"
								bind:value={editTitle}
								class="input w-full border-[#E8E0D8] bg-white text-[#2D2724] input-sm dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-artist"
								class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">Artist</label
							>
							<input
								id="edit-artist"
								type="text"
								bind:value={editArtist}
								class="input w-full border-[#E8E0D8] bg-white text-[#2D2724] input-sm dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-album"
								class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">Album</label
							>
							<input
								id="edit-album"
								type="text"
								bind:value={editAlbum}
								class="input w-full border-[#E8E0D8] bg-white text-[#2D2724] input-sm dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-album-artist"
								class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]"
								>Album Artist</label
							>
							<input
								id="edit-album-artist"
								type="text"
								bind:value={editAlbumArtist}
								class="input w-full border-[#E8E0D8] bg-white text-[#2D2724] input-sm dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-genre"
								class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">Genre</label
							>
							<input
								id="edit-genre"
								type="text"
								bind:value={editGenre}
								class="input w-full border-[#E8E0D8] bg-white text-[#2D2724] input-sm dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-year"
								class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">Year</label
							>
							<input
								id="edit-year"
								type="number"
								bind:value={editYear}
								class="input w-full border-[#E8E0D8] bg-white font-mono text-[#2D2724] input-sm dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-track"
								class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">Track #</label
							>
							<input
								id="edit-track"
								type="number"
								bind:value={editTrackNumber}
								class="input w-full border-[#E8E0D8] bg-white font-mono text-[#2D2724] input-sm dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-disc"
								class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">Disc #</label
							>
							<input
								id="edit-disc"
								type="number"
								bind:value={editDiscNumber}
								class="input w-full border-[#E8E0D8] bg-white font-mono text-[#2D2724] input-sm dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div class="sm:col-span-2">
							<label
								for="edit-composer"
								class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">Composer</label
							>
							<input
								id="edit-composer"
								type="text"
								bind:value={editComposer}
								class="input w-full border-[#E8E0D8] bg-white text-[#2D2724] input-sm dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div class="sm:col-span-2">
							<label
								for="edit-lyrics"
								class="label text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">Lyrics</label
							>
							<textarea
								id="edit-lyrics"
								bind:value={editLyrics}
								rows="3"
								class="textarea-bordered textarea w-full border-[#E8E0D8] bg-white text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							></textarea>
						</div>
					</div>

					<div
						class="modal-action mt-6 justify-between border-t border-[#E8E0D8] pt-4 dark:border-white/10"
					>
						<button
							class="btn btn-ghost text-[#2D2724] btn-sm dark:text-[#F9F6F2]"
							onclick={() => (activeTab = 'overview')}
						>
							Cancel
						</button>
						<button
							class="hero-gradient btn rounded-full border-none px-5 text-xs text-white shadow-md btn-sm"
							onclick={saveMetadata}
							disabled={editLoading}
						>
							{#if editLoading}
								<span class="loading loading-xs loading-spinner"></span>
							{/if}
							Save Changes
						</button>
					</div>
				</div>
			{/if}
		{/if}
	</div>
</dialog>
