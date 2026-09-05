<script lang="ts">
	/* eslint-disable @typescript-eslint/no-unused-vars */
	/* eslint-disable svelte/no-navigation-without-resolve, svelte/prefer-svelte-reactivity */
	import { onMount } from 'svelte';
	import { api, API_BASE_URL } from '$lib/api/client';

	interface Song {
		id: number;
		album?: string;
		artist?: string;
		year?: number;
	}

	interface AlbumCard {
		name: string;
		artist: string;
		year?: number;
		songCount: number;
		sampleSongId: number;
	}

	let albums = $state<AlbumCard[]>([]);
	let loading = $state(true);

	onMount(async () => {
		try {
			const res = await api.get<{ items: Song[] }>('/songs?limit=200');
			const albumMap = new Map<string, AlbumCard>();

			for (const song of res.items) {
				const albumName = song.album || 'Unknown Album';
				if (!albumMap.has(albumName)) {
					albumMap.set(albumName, {
						name: albumName,
						artist: song.artist || 'Unknown Artist',
						year: song.year,
						songCount: 1,
						sampleSongId: song.id
					});
				} else {
					const existing = albumMap.get(albumName)!;
					existing.songCount++;
				}
			}
			albums = Array.from(albumMap.values());
		} catch (err) {
			console.error('Failed to load albums:', err);
		} finally {
			loading = false;
		}
	});
</script>

<div class="space-y-6">
	<div>
		<h1 class="text-3xl font-extrabold tracking-tight text-[#2D2724] dark:text-[#F9F6F2]">
			Albums
		</h1>
		<p class="text-sm font-medium text-[#655E59] dark:text-[#D1C9C3]">
			Browsing indexed albums collection
		</p>
	</div>

	{#if loading}
		<div class="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
			{#each Array.from({ length: 10 }) as _, idx (idx)}
				<div class="h-56 w-full skeleton rounded-2xl"></div>
			{/each}
		</div>
	{:else if albums.length === 0}
		<div class="alert alert-info shadow-sm">No albums indexed yet. Run a directory scan first.</div>
	{:else}
		<div class="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
			{#each albums as album (album.name)}
				<a
					href={`/songs?search=${encodeURIComponent(album.name)}`}
					class="glass-card group flex flex-col justify-between rounded-3xl p-4 shadow-sm transition-all duration-300 ease-out hover:-translate-y-1.5 hover:border-[#C97B45]/40 hover:shadow-xl"
				>
					<figure
						class="mb-3 aspect-square w-full overflow-hidden rounded-2xl border border-[#E8E0D8] dark:border-white/10"
					>
						<img
							src={`${API_BASE_URL}/songs/${album.sampleSongId}/cover`}
							alt={album.name}
							class="h-full w-full object-cover transition-transform duration-300 ease-out group-hover:scale-105"
						/>
					</figure>
					<div>
						<h3 class="truncate text-sm font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">
							{album.name}
						</h3>
						<p class="truncate text-xs font-bold text-[#A85828] dark:text-[#E58E53]">
							{album.artist}
						</p>
						<div
							class="mt-2 flex items-center justify-between text-xs font-medium text-[#655E59] dark:text-[#D1C9C3]"
						>
							<span>{album.songCount} track{album.songCount > 1 ? 's' : ''}</span>
							<span>{album.year || ''}</span>
						</div>
					</div>
				</a>
			{/each}
		</div>
	{/if}
</div>
