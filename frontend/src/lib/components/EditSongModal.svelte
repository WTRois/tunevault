<script lang="ts">
	import { editModal } from '$lib/stores/editModal.svelte';
	import { player } from '$lib/stores/player.svelte';
	import { api, API_BASE_URL } from '$lib/api/client';
	import { Edit3, Upload, Trash2, X, Music2 } from '@lucide/svelte';
	import { toast } from '$lib/stores/toast.svelte';

	interface SongDetail {
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

	let songDetail = $state<SongDetail | null>(null);
	let loading = $state(false);
	let editLoading = $state(false);

	// Form fields
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

	// Cover Image upload
	let coverFile = $state<File | null>(null);
	let coverPreview = $state<string | null>(null);
	let isDragOver = $state(false);

	$effect(() => {
		if (editModal.isOpen && editModal.songId) {
			loadSongDetails(editModal.songId);
		} else {
			resetForm();
		}
	});

	async function loadSongDetails(id: number) {
		loading = true;
		try {
			const data = await api.get<SongDetail>(`/songs/${id}`);
			songDetail = data;

			// Populate Form State
			editTitle = data.title || '';
			editArtist = data.artist || '';
			editAlbum = data.album || '';
			editAlbumArtist = data.album_artist || '';
			editGenre = data.genre || '';
			editYear = data.year;
			editTrackNumber = data.track_number;
			editDiscNumber = data.disc_number;
			editComposer = data.composer || '';
			editLyrics = data.lyrics || '';

			coverFile = null;
			coverPreview = null;
		} catch (err) {
			console.error('Failed to fetch song details for editing:', err);
		} finally {
			loading = false;
		}
	}

	function resetForm() {
		songDetail = null;
		coverFile = null;
		coverPreview = null;
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

	async function saveMetadata() {
		if (!songDetail) return;
		editLoading = true;

		try {
			// 1. Save Text Metadata
			const updated = await api.put<SongDetail>(`/songs/${songDetail.id}/metadata`, {
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
			let latestSha256 = updated.sha256;
			let latestHasCover = updated.has_cover;
			if (coverFile) {
				const formData = new FormData();
				formData.append('file', coverFile);
				const res = await fetch(`${API_BASE_URL}/songs/${songDetail.id}/cover`, {
					method: 'POST',
					body: formData
				});
				if (!res.ok) throw new Error('Failed to upload cover image');
				const coverResult = (await res.json()) as { sha256: string; has_cover: boolean };
				latestSha256 = coverResult.sha256;
				latestHasCover = coverResult.has_cover;
			}

			songDetail = { ...updated, sha256: latestSha256, has_cover: latestHasCover };

			// 3. Update currently playing track live, including its cache-busting hash.
			if (player.currentTrack && player.currentTrack.id === updated.id) {
				player.updateTrack({
					...player.currentTrack,
					title: updated.title,
					artist: updated.artist,
					album: updated.album,
					sha256: latestSha256
				});
			}

			toast.success('Metadata berhasil disimpan ke file audio dan katalog.');
			editModal.notifySave();
		} catch (err) {
			toast.error((err as Error).message || 'Gagal memperbarui metadata.');
		} finally {
			editLoading = false;
		}
	}

	async function removeCover() {
		if (!songDetail) return;
		if (!confirm('Remove embedded cover art from audio file?')) return;
		try {
			const result = await api.delete<{ sha256: string; has_cover: boolean }>(
				`/songs/${songDetail.id}/cover`
			);
			coverFile = null;
			coverPreview = null;
			songDetail = { ...songDetail, sha256: result.sha256, has_cover: result.has_cover };

			if (player.currentTrack && player.currentTrack.id === songDetail.id) {
				player.updateTrack({ ...player.currentTrack, sha256: result.sha256 });
			}

			toast.success('Cover art berhasil dihapus.');
			editModal.notifySave();
		} catch (err) {
			toast.error((err as Error).message || 'Gagal menghapus cover art.');
		}
	}
</script>

{#if editModal.isOpen}
	<dialog class="modal modal-open">
		<div class="glass-panel modal-box max-w-2xl rounded-3xl p-6 shadow-2xl dark:bg-[#1E1917]">
			<button
				class="btn absolute top-4 right-4 btn-circle btn-ghost text-[#2D2724] btn-sm dark:text-[#F9F6F2]"
				onclick={() => editModal.close()}
				aria-label="Close edit modal"
			>
				<X class="h-4 w-4" />
			</button>

			<h3 class="flex items-center gap-2 text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">
				<Edit3 class="h-5 w-5 text-[#C97B45]" />
				Edit Audio Metadata & Cover
			</h3>

			{#if loading}
				<div class="flex items-center justify-center py-12">
					<span class="loading loading-lg loading-spinner text-[#C97B45]"></span>
				</div>
			{:else if songDetail}
				<div class="mt-4 space-y-4">
					<!-- Cover Art Drag-and-Drop Uploader -->
					<div class="flex flex-col gap-4 sm:flex-row sm:items-center">
						<div
							class="relative flex h-28 w-28 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-[#E8E0D8] bg-[#F2ECE7] shadow-sm dark:border-white/10 dark:bg-white/10"
						>
							{#if coverPreview}
								<img
									src={coverPreview}
									alt="New Cover Preview"
									class="h-full w-full object-cover"
								/>
							{:else}
								<img
									src={`${API_BASE_URL}/songs/${songDetail.id}/cover?t=${songDetail.sha256}`}
									alt={songDetail.title || songDetail.filename}
									class="h-full w-full object-cover"
									onerror={(e) => {
										const target = e.target as HTMLImageElement;
										target.style.display = 'none';
									}}
								/>
								<Music2 class="absolute -z-10 h-8 w-8 text-[#9A6548] dark:text-[#E58E53]" />
							{/if}
						</div>

						<div
							class={`flex flex-1 flex-col items-center justify-center rounded-2xl border-2 border-dashed p-4 text-center transition-all ${
								isDragOver
									? 'border-[#C97B45] bg-[#C97B45]/10'
									: 'border-[#E8E0D8] bg-[#F2ECE7]/50 dark:border-white/20 dark:bg-white/5'
							}`}
							ondragover={(e) => {
								e.preventDefault();
								isDragOver = true;
							}}
							ondragleave={() => (isDragOver = false)}
							ondrop={handleCoverDrop}
							role="region"
							aria-label="Cover artwork drag and drop area"
						>
							<Upload class="mb-1 h-6 w-6 text-[#C97B45]" />
							<p class="text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]">
								Drag & Drop new Cover Art image here
							</p>
							<label
								for="modal-cover-input"
								class="mt-1 cursor-pointer text-[11px] text-[#857D78] underline hover:text-[#C97B45] dark:text-[#D1C9C3]"
							>
								or click to browse (.jpg, .png, .webp)
							</label>
							<input
								id="modal-cover-input"
								type="file"
								accept="image/*"
								class="hidden"
								onchange={handleCoverSelect}
							/>

							{#if songDetail.has_cover || coverPreview}
								<button
									class="btn mt-2 gap-1 btn-ghost text-[11px] text-error btn-xs hover:bg-error/10"
									onclick={removeCover}
								>
									<Trash2 class="h-3.5 w-3.5" /> Remove Cover Art
								</button>
							{/if}
						</div>
					</div>

					<!-- Metadata Form Inputs -->
					<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
						<div>
							<label
								for="edit-title"
								class="label text-[11px] font-bold text-[#5B534F] dark:text-[#D1C9C3]">Title</label
							>
							<input
								id="edit-title"
								type="text"
								bind:value={editTitle}
								class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-artist"
								class="label text-[11px] font-bold text-[#5B534F] dark:text-[#D1C9C3]">Artist</label
							>
							<input
								id="edit-artist"
								type="text"
								bind:value={editArtist}
								class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-album"
								class="label text-[11px] font-bold text-[#5B534F] dark:text-[#D1C9C3]">Album</label
							>
							<input
								id="edit-album"
								type="text"
								bind:value={editAlbum}
								class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-album-artist"
								class="label text-[11px] font-bold text-[#5B534F] dark:text-[#D1C9C3]"
								>Album Artist</label
							>
							<input
								id="edit-album-artist"
								type="text"
								bind:value={editAlbumArtist}
								class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-genre"
								class="label text-[11px] font-bold text-[#5B534F] dark:text-[#D1C9C3]">Genre</label
							>
							<input
								id="edit-genre"
								type="text"
								bind:value={editGenre}
								class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-year"
								class="label text-[11px] font-bold text-[#5B534F] dark:text-[#D1C9C3]">Year</label
							>
							<input
								id="edit-year"
								type="number"
								bind:value={editYear}
								class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-track-no"
								class="label text-[11px] font-bold text-[#5B534F] dark:text-[#D1C9C3]"
								>Track #</label
							>
							<input
								id="edit-track-no"
								type="number"
								bind:value={editTrackNumber}
								class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>

						<div>
							<label
								for="edit-disc-no"
								class="label text-[11px] font-bold text-[#5B534F] dark:text-[#D1C9C3]">Disc #</label
							>
							<input
								id="edit-disc-no"
								type="number"
								bind:value={editDiscNumber}
								class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
							/>
						</div>
					</div>

					<div>
						<label
							for="edit-composer"
							class="label text-[11px] font-bold text-[#5B534F] dark:text-[#D1C9C3]">Composer</label
						>
						<input
							id="edit-composer"
							type="text"
							bind:value={editComposer}
							class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
						/>
					</div>

					<div>
						<label
							for="edit-lyrics"
							class="label text-[11px] font-bold text-[#5B534F] dark:text-[#D1C9C3]">Lyrics</label
						>
						<textarea
							id="edit-lyrics"
							bind:value={editLyrics}
							rows="3"
							class="textarea-bordered textarea w-full border-[#E8E0D8] bg-white/80 text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
						></textarea>
					</div>
				</div>

				<div class="modal-action mt-6">
					<button
						class="btn btn-ghost text-xs text-[#2D2724] btn-sm dark:text-[#F9F6F2]"
						onclick={() => editModal.close()}>Cancel</button
					>
					<button
						class="hero-gradient btn rounded-full border-none px-6 text-xs text-white shadow-md btn-sm"
						onclick={saveMetadata}
						disabled={editLoading}
					>
						{#if editLoading}
							<span class="loading loading-xs loading-spinner"></span>
						{/if}
						Save Changes
					</button>
				</div>
			{/if}
		</div>
	</dialog>
{/if}
