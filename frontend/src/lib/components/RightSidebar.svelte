<script lang="ts">
	import { api, API_BASE_URL } from '$lib/api/client';
	import { editModal } from '$lib/stores/editModal.svelte';
	import { player } from '$lib/stores/player.svelte';
	import { formatDuration } from '$lib/utils/os';
	import {
		Check,
		Disc,
		Edit3,
		ExternalLink,
		FileText,
		Music2,
		Search,
		SlidersHorizontal,
		Sparkles
	} from '@lucide/svelte';

	interface SongDetail {
		id: number;
		title?: string;
		artist?: string;
		album?: string;
		album_artist?: string;
		genre?: string;
		year?: number;
		duration?: number;
		codec?: string;
		lyrics?: string;
		sha256: string;
	}

	interface LyricsCandidate {
		track_name: string;
		artist_name: string;
		album_name?: string;
		plain_lyrics?: string;
		synced_lyrics?: string;
	}

	interface YouTubeCandidate {
		video_id: string;
		video_url: string;
		title: string;
		artist?: string;
		album?: string;
		year?: number;
		thumbnail_url?: string;
		channel?: string;
		match_score: number;
	}

	const metadataFields = [
		{ key: 'title', label: 'Title' },
		{ key: 'artist', label: 'Artist' },
		{ key: 'album', label: 'Album' },
		{ key: 'year', label: 'Year' }
	] as const;

	let songDetail = $state<SongDetail | null>(null);
	let lyricsLoading = $state(false);
	let lyricsError = $state('');
	let lyricsPreview = $state<LyricsCandidate | null>(null);
	let lyricsCandidates = $state<LyricsCandidate[]>([]);
	let lyricsSaving = $state(false);
	let metadataLoading = $state(false);
	let metadataError = $state('');
	let metadataCandidates = $state<YouTubeCandidate[]>([]);
	let selectedCandidate = $state<YouTubeCandidate | null>(null);
	let selectedFields = $state<Record<string, boolean>>({});
	let metadataSaving = $state(false);

	$effect(() => {
		const trackId = player.currentTrack?.id;
		if (trackId) void loadSongDetail(trackId);
		else resetInspector();
	});

	async function loadSongDetail(songId: number) {
		try {
			const detail = await api.get<SongDetail>(`/songs/${songId}`);
			if (player.currentTrack?.id === songId) songDetail = detail;
		} catch {
			songDetail = null;
		}
	}

	function resetInspector() {
		songDetail = null;
		lyricsPreview = null;
		lyricsCandidates = [];
		lyricsError = '';
		metadataCandidates = [];
		metadataError = '';
		selectedCandidate = null;
		selectedFields = {};
	}

	async function fetchLyrics() {
		if (!player.currentTrack) return;
		lyricsLoading = true;
		lyricsError = '';
		lyricsPreview = null;
		lyricsCandidates = [];
		try {
			const result = await api.post<{
				lyrics?: LyricsCandidate;
				candidates?: LyricsCandidate[];
			}>(`/songs/${player.currentTrack.id}/lyrics/fetch`);
			lyricsPreview = result.lyrics || null;
			lyricsCandidates = result.candidates || [];
		} catch (error) {
			lyricsError = (error as Error).message;
		} finally {
			lyricsLoading = false;
		}
	}

	async function embedLyrics() {
		if (!player.currentTrack || !lyricsPreview) return;
		const lyrics = lyricsPreview.plain_lyrics || lyricsPreview.synced_lyrics;
		if (!lyrics) return;
		lyricsSaving = true;
		try {
			const updated = await api.put<SongDetail>(`/songs/${player.currentTrack.id}/lyrics`, {
				lyrics
			});
			songDetail = updated;
			player.updateTrack({ ...player.currentTrack, sha256: updated.sha256 });
			lyricsPreview = null;
			lyricsCandidates = [];
		} catch (error) {
			lyricsError = (error as Error).message;
		} finally {
			lyricsSaving = false;
		}
	}

	async function searchMetadata() {
		if (!player.currentTrack) return;
		metadataLoading = true;
		metadataError = '';
		metadataCandidates = [];
		selectedCandidate = null;
		try {
			const result = await api.post<{ candidates: YouTubeCandidate[] }>(
				`/songs/${player.currentTrack.id}/metadata-match/search`
			);
			metadataCandidates = result.candidates;
		} catch (error) {
			metadataError = (error as Error).message;
		} finally {
			metadataLoading = false;
		}
	}

	function selectCandidate(candidate: YouTubeCandidate) {
		selectedCandidate = candidate;
		selectedFields = {
			title: true,
			artist: Boolean(candidate.artist),
			album: Boolean(candidate.album),
			year: Boolean(candidate.year)
		};
	}

	async function embedMetadata() {
		if (!player.currentTrack || !selectedCandidate) return;
		const metadata: Record<string, string | number> = {};
		for (const field of metadataFields) {
			if (!selectedFields[field.key]) continue;
			const value = selectedCandidate[field.key as keyof YouTubeCandidate];
			if (typeof value === 'string' || typeof value === 'number') metadata[field.key] = value;
		}
		if (!Object.keys(metadata).length) return;
		metadataSaving = true;
		try {
			const updated = await api.put<SongDetail>(`/songs/${player.currentTrack.id}/metadata-match`, {
				video_id: selectedCandidate.video_id,
				metadata
			});
			songDetail = updated;
			player.updateTrack({
				...player.currentTrack,
				title: updated.title,
				artist: updated.artist,
				album: updated.album,
				sha256: updated.sha256
			});
			selectedCandidate = null;
		} catch (error) {
			metadataError = (error as Error).message;
		} finally {
			metadataSaving = false;
		}
	}

	function openYouTube(candidate: YouTubeCandidate) {
		window.open(candidate.video_url, '_blank', 'noopener,noreferrer');
	}
</script>

<aside
	class="glass-panel hidden min-h-full w-[300px] shrink-0 flex-col gap-6 border-l border-[#E8E0D8] p-5 xl:flex"
>
	<div
		class="flex items-center justify-between gap-2 border-b border-[#E8E0D8] pb-3 dark:border-white/10"
	>
		<h2
			class="flex items-center gap-1.5 truncate text-xs font-extrabold tracking-wider text-[#2D2724] uppercase dark:text-[#F9F6F2]"
		>
			<SlidersHorizontal class="h-4 w-4 shrink-0 text-[#C97B45]" /> Track Inspector
		</h2>
		<span
			class="badge shrink-0 border-none bg-[#8E9570] px-2 py-0.5 badge-sm text-[10px] font-semibold whitespace-nowrap text-white"
			>Audio Specs</span
		>
	</div>

	{#if player.currentTrack}
		<div class="space-y-4">
			<div
				class="group relative aspect-square overflow-hidden rounded-2xl border border-[#E8E0D8] shadow-xl dark:border-white/10"
			>
				<img
					src={`${API_BASE_URL}/songs/${player.currentTrack.id}/cover?t=${player.currentTrack.sha256}`}
					alt={player.currentTrack.title || player.currentTrack.filename}
					class="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
				/>
				<div
					class="absolute inset-0 flex items-center justify-center bg-black/20 opacity-0 transition-opacity group-hover:opacity-100"
				>
					<Disc class="animate-spin-slow h-12 w-12 text-white" />
				</div>
			</div>
			<div class="space-y-1">
				<div class="flex items-start justify-between gap-2">
					<h3 class="truncate text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">
						{player.currentTrack.title || player.currentTrack.filename}
					</h3>
					<button
						class="btn btn-circle btn-ghost text-[#857D78] btn-xs"
						onclick={() => editModal.open(player.currentTrack!.id)}
						title="Edit metadata"
						aria-label="Edit metadata"><Edit3 class="h-4 w-4" /></button
					>
				</div>
				<p class="truncate text-sm font-semibold text-[#C97B45]">
					{player.currentTrack.artist || 'Unknown Artist'}
				</p>
				<p class="truncate text-xs text-[#857D78] dark:text-[#D1C9C3]">
					{player.currentTrack.album || 'Unknown Album'}
				</p>
			</div>
		</div>

		<div class="space-y-3">
			<h4 class="text-xs font-bold tracking-wider text-[#857D78] uppercase dark:text-[#D1C9C3]">
				Extended Audio Specs
			</h4>
			<div class="grid grid-cols-2 gap-2 font-mono text-xs">
				<div class="glass-card rounded-xl p-3">
					<span class="block text-[10px] text-[#857D78]">Duration</span><span
						class="font-bold text-[#2D2724] dark:text-[#F9F6F2]"
						>{formatDuration(player.currentTrack.duration)}</span
					>
				</div>
				<div class="glass-card rounded-xl p-3">
					<span class="block text-[10px] text-[#857D78]">Format</span><span
						class="font-bold text-[#2D2724] uppercase dark:text-[#F9F6F2]">Audio</span
					>
				</div>
			</div>
		</div>

		<div class="space-y-3">
			<div class="flex items-center justify-between">
				<h4
					class="flex items-center gap-1.5 text-xs font-bold tracking-wider text-[#857D78] uppercase dark:text-[#D1C9C3]"
				>
					<FileText class="h-3.5 w-3.5 text-[#C97B45]" /> Lyrics
				</h4>
				{#if !songDetail?.lyrics && !lyricsPreview}<button
						class="btn btn-ghost btn-xs"
						onclick={fetchLyrics}
						disabled={lyricsLoading}
						>{#if lyricsLoading}<span class="loading loading-xs loading-spinner"
							></span>{:else}Fetch{/if}</button
					>{/if}
			</div>
			{#if songDetail?.lyrics}
				<div
					class="max-h-48 overflow-y-auto rounded-xl bg-[#F2ECE7]/70 p-3 text-xs leading-relaxed whitespace-pre-wrap text-[#2D2724] dark:bg-white/5 dark:text-[#F9F6F2]"
				>
					{songDetail.lyrics}
				</div>
			{:else if lyricsPreview}
				<div class="space-y-2">
					<div
						class="max-h-32 overflow-y-auto rounded-xl bg-[#F2ECE7]/70 p-3 text-xs leading-relaxed whitespace-pre-wrap dark:bg-white/5"
					>
						{lyricsPreview.plain_lyrics || lyricsPreview.synced_lyrics}
					</div>
					<button
						class="hero-gradient btn w-full text-white btn-xs"
						onclick={embedLyrics}
						disabled={lyricsSaving}
						>{#if lyricsSaving}<span class="loading loading-xs loading-spinner"></span>{:else}<Check
								class="h-3 w-3"
							/> Embed Lyrics{/if}</button
					>
				</div>
			{:else if lyricsCandidates.length}
				<div class="space-y-1.5">
					{#each lyricsCandidates as candidate (candidate.track_name)}
						<button
							class="w-full rounded-lg border border-[#E8E0D8] p-2 text-left text-xs hover:border-[#C97B45] dark:border-white/10"
							onclick={() => (lyricsPreview = candidate)}
						>
							<strong>{candidate.track_name}</strong>
							<span class="block text-[#857D78]"
								>{candidate.artist_name} · {candidate.album_name || 'Unknown album'}</span
							>
						</button>
					{/each}
				</div>
			{:else if lyricsError}
				<p class="text-xs text-error">{lyricsError}</p>
			{:else}
				<p class="text-xs text-[#857D78] dark:text-[#D1C9C3]">No lyrics embedded yet.</p>
			{/if}
		</div>

		<div class="space-y-3">
			<div class="flex items-center justify-between">
				<h4
					class="flex items-center gap-1.5 text-xs font-bold tracking-wider text-[#857D78] uppercase dark:text-[#D1C9C3]"
				>
					<Search class="h-3.5 w-3.5 text-[#C97B45]" /> Metadata & Video
				</h4>
				<button class="btn btn-ghost btn-xs" onclick={searchMetadata} disabled={metadataLoading}
					>{#if metadataLoading}<span class="loading loading-xs loading-spinner"
						></span>{:else}Find{/if}</button
				>
			</div>
			{#if selectedCandidate}
				<div class="space-y-2 rounded-xl border border-[#C97B45]/40 p-2 text-xs">
					<div class="flex gap-2">
						{#if selectedCandidate.thumbnail_url}<img
								src={selectedCandidate.thumbnail_url}
								alt=""
								class="h-12 w-20 rounded object-cover"
							/>{/if}
						<div>
							<strong>{selectedCandidate.title}</strong><span class="block text-[#857D78]"
								>{selectedCandidate.channel || selectedCandidate.artist || 'YouTube'}</span
							>
						</div>
					</div>
					{#each metadataFields as field (field.key)}{#if selectedCandidate[field.key as keyof YouTubeCandidate] !== undefined}<label
								class="flex items-center gap-2"
								><input
									class="checkbox checkbox-xs"
									type="checkbox"
									bind:checked={selectedFields[field.key]}
								/>
								{field.label}: {selectedCandidate[field.key as keyof YouTubeCandidate]}</label
							>{/if}{/each}
					<div class="flex gap-2">
						<button
							class="btn flex-1 btn-outline btn-xs"
							onclick={() => openYouTube(selectedCandidate!)}
						>
							<ExternalLink class="h-3 w-3" /> YouTube
						</button><button
							class="hero-gradient btn flex-1 text-white btn-xs"
							onclick={embedMetadata}
							disabled={metadataSaving}>Embed</button
						>
					</div>
				</div>
			{:else if metadataCandidates.length}
				<div class="space-y-1.5">
					{#each metadataCandidates as candidate (candidate.video_id)}
						<button
							class="w-full rounded-lg border border-[#E8E0D8] p-2 text-left text-xs hover:border-[#C97B45] dark:border-white/10"
							onclick={() => selectCandidate(candidate)}
						>
							<strong class="line-clamp-2">{candidate.title}</strong>
							<span class="block text-[#857D78]"
								>{candidate.channel || candidate.artist || 'Unknown'} · {Math.round(
									candidate.match_score * 100
								)}% match</span
							>
						</button>
					{/each}
				</div>
			{:else if metadataError}<p class="text-xs text-error">{metadataError}</p>{:else}<p
					class="text-xs text-[#857D78] dark:text-[#D1C9C3]"
				>
					Find matching metadata and a YouTube video.
				</p>
			{/if}
		</div>
	{:else}
		<div
			class="flex flex-1 flex-col items-center justify-center space-y-3 py-12 text-center text-[#857D78] dark:text-[#D1C9C3]"
		>
			<div
				class="flex h-16 w-16 items-center justify-center rounded-2xl bg-[#F2ECE7] text-[#9A6548] dark:bg-white/10 dark:text-[#E58E53]"
			>
				<Music2 class="h-8 w-8" />
			</div>
			<div>
				<h3 class="text-sm font-bold text-[#2D2724] dark:text-[#F9F6F2]">No Track Selected</h3>
				<p class="mt-1 max-w-[200px] text-xs">
					Select or play any track from your library to inspect metadata
				</p>
			</div>
			<span class="badge gap-1 badge-outline"
				><Sparkles class="h-3 w-3 text-[#D8D66A]" /> Ready</span
			>
		</div>
	{/if}
</aside>
