<script lang="ts">
	/* eslint-disable @typescript-eslint/no-unused-vars, svelte/no-navigation-without-resolve, svelte/prefer-svelte-reactivity */
	import { onMount } from 'svelte';
	import { api } from '$lib/api/client';

	interface Song {
		genre?: string;
	}

	let genres = $state<{ name: string; count: number }[]>([]);
	let loading = $state(true);

	onMount(async () => {
		try {
			const res = await api.get<{ items: Song[] }>('/songs?limit=1000');
			const genreMap = new Map<string, number>();

			for (const song of res.items) {
				const g = song.genre || 'Uncategorized';
				genreMap.set(g, (genreMap.get(g) || 0) + 1);
			}

			genres = Array.from(genreMap.entries()).map(([name, count]) => ({ name, count }));
		} catch (err) {
			console.error('Failed to load genres:', err);
		} finally {
			loading = false;
		}
	});
</script>

<div class="space-y-6">
	<div>
		<h1 class="text-3xl font-extrabold tracking-tight text-[#2D2724] dark:text-[#F9F6F2]">
			Genres
		</h1>
		<p class="text-sm font-medium text-[#655E59] dark:text-[#D1C9C3]">Musical genre categories</p>
	</div>

	{#if loading}
		<div class="flex flex-wrap gap-3">
			{#each Array.from({ length: 8 }) as _, idx (idx)}
				<div class="h-12 w-32 skeleton rounded-full"></div>
			{/each}
		</div>
	{:else if genres.length === 0}
		<div
			class="rounded-3xl border border-[#C97B45]/30 bg-[#C97B45]/10 p-6 text-sm font-medium text-[#6E4330] shadow-sm dark:bg-[#C97B45]/20 dark:text-[#F3D9C9]"
		>
			No genres categorized yet. Run a directory scan to index your music.
		</div>
	{:else}
		<div class="flex flex-wrap gap-3">
			{#each genres as genre (genre.name)}
				<a
					href={`/songs?search=${encodeURIComponent(genre.name)}`}
					class="btn gap-2 rounded-full border-[#E8E0D8] bg-[#F2ECE7] text-[#2D2724] transition-all duration-200 ease-in-out btn-md hover:scale-105 hover:border-none hover:bg-[#C97B45] hover:text-white dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2] dark:hover:bg-[#C97B45]"
				>
					<span class="font-bold">{genre.name}</span>
					<span class="badge border-none bg-[#8E9570] badge-sm text-white">{genre.count}</span>
				</a>
			{/each}
		</div>
	{/if}
</div>
