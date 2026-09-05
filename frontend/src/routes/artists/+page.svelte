<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve, svelte/prefer-svelte-reactivity, @typescript-eslint/no-unused-vars */
	import { onMount } from 'svelte';
	import { api } from '$lib/api/client';

	interface Song {
		id: number;
		artist?: string;
		album?: string;
	}

	interface ArtistCard {
		name: string;
		songCount: number;
		albums: Set<string>;
	}

	let artists = $state<{ name: string; songCount: number; albumCount: number }[]>([]);
	let loading = $state(true);

	onMount(async () => {
		try {
			const res = await api.get<{ items: Song[] }>('/songs?limit=500');
			const artistMap = new Map<string, ArtistCard>();

			for (const song of res.items) {
				const artistName = song.artist || 'Unknown Artist';
				if (!artistMap.has(artistName)) {
					artistMap.set(artistName, {
						name: artistName,
						songCount: 1,
						albums: new Set(song.album ? [song.album] : [])
					});
				} else {
					const existing = artistMap.get(artistName)!;
					existing.songCount++;
					if (song.album) existing.albums.add(song.album);
				}
			}

			artists = Array.from(artistMap.values()).map((a) => ({
				name: a.name,
				songCount: a.songCount,
				albumCount: a.albums.size
			}));
		} catch (err) {
			console.error('Failed to load artists:', err);
		} finally {
			loading = false;
		}
	});
</script>

<div class="space-y-6">
	<div>
		<h1 class="text-3xl font-extrabold tracking-tight text-[#2D2724] dark:text-[#F9F6F2]">
			Artists
		</h1>
		<p class="text-sm font-medium text-[#655E59] dark:text-[#D1C9C3]">Indexed artists breakdown</p>
	</div>

	{#if loading}
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
			{#each Array.from({ length: 6 }) as _, idx (idx)}
				<div class="h-24 w-full skeleton rounded-2xl"></div>
			{/each}
		</div>
	{:else if artists.length === 0}
		<div
			class="rounded-3xl border border-[#C97B45]/30 bg-[#C97B45]/10 p-6 text-sm font-medium text-[#6E4330] shadow-sm dark:bg-[#C97B45]/20 dark:text-[#F3D9C9]"
		>
			No artists indexed yet. Run a directory scan to index your music.
		</div>
	{:else}
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
			{#each artists as artist (artist.name)}
				<a
					href={`/songs?search=${encodeURIComponent(artist.name)}`}
					class="glass-card group flex flex-row items-center gap-4 rounded-3xl p-4 shadow-sm transition-all duration-300 ease-out hover:-translate-y-1 hover:border-[#C97B45]/40 hover:shadow-lg"
				>
					<div class="placeholder avatar shrink-0">
						<div
							class="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#C97B45] text-lg font-bold text-white shadow-sm transition-transform duration-300 group-hover:scale-105"
						>
							{artist.name.charAt(0).toUpperCase()}
						</div>
					</div>
					<div class="min-w-0">
						<h3 class="truncate text-base font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">
							{artist.name}
						</h3>
						<p class="truncate text-xs font-medium text-[#655E59] dark:text-[#D1C9C3]">
							{artist.songCount} track{artist.songCount > 1 ? 's' : ''} • {artist.albumCount} album{artist.albumCount >
							1
								? 's'
								: ''}
						</p>
					</div>
				</a>
			{/each}
		</div>
	{/if}
</div>
