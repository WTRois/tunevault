<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api, API_BASE_URL } from '$lib/api/client';
	import { player } from '$lib/stores/player.svelte';
	import { formatDuration } from '$lib/utils/os';
	import { Sun, Moon, Search, FolderPlus, Menu, Music2, Play, ArrowRight } from '@lucide/svelte';

	interface SearchSong {
		id: number;
		title?: string;
		artist?: string;
		album?: string;
		duration?: number;
		filename: string;
		sha256: string;
	}

	let { onToggleSidebar, onOpenScanModal } = $props<{
		onToggleSidebar?: () => void;
		onOpenScanModal?: () => void;
	}>();

	let currentTheme = $state<'tunevault' | 'dark'>('dark');
	let searchQuery = $state('');
	let searchResults = $state<SearchSong[]>([]);
	let totalResults = $state(0);
	let searchLoading = $state(false);
	let isDropdownOpen = $state(false);

	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	let searchInputEl = $state<HTMLInputElement | null>(null);
	let containerEl = $state<HTMLDivElement | null>(null);

	onMount(() => {
		const savedTheme = (localStorage.getItem('tunevault_theme') as 'tunevault' | 'dark') || 'dark';
		currentTheme = savedTheme;
		applyTheme(savedTheme);

		function handleKeyDown(e: KeyboardEvent) {
			if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
				e.preventDefault();
				searchInputEl?.focus();
				searchInputEl?.select();
			}
		}

		function handleClickOutside(e: MouseEvent) {
			if (containerEl && !containerEl.contains(e.target as Node)) {
				isDropdownOpen = false;
			}
		}

		window.addEventListener('keydown', handleKeyDown);
		window.addEventListener('click', handleClickOutside);
		return () => {
			window.removeEventListener('keydown', handleKeyDown);
			window.removeEventListener('click', handleClickOutside);
		};
	});

	function applyTheme(theme: 'tunevault' | 'dark') {
		if (typeof document !== 'undefined') {
			document.documentElement.setAttribute('data-theme', theme);
			if (theme === 'dark') {
				document.documentElement.classList.add('dark');
			} else {
				document.documentElement.classList.remove('dark');
			}
		}
	}

	function handleInput() {
		if (debounceTimer) clearTimeout(debounceTimer);

		if (!searchQuery.trim()) {
			searchResults = [];
			totalResults = 0;
			isDropdownOpen = false;
			return;
		}

		searchLoading = true;
		isDropdownOpen = true;

		debounceTimer = setTimeout(async () => {
			try {
				const res = await api.get<{ items: SearchSong[]; total: number }>(
					`/songs?search=${encodeURIComponent(searchQuery.trim())}&limit=5`
				);
				searchResults = res.items;
				totalResults = res.total;
			} catch (err) {
				console.error('Failed to perform live search:', err);
			} finally {
				searchLoading = false;
			}
		}, 200);
	}

	function handleSongClick(song: SearchSong) {
		player.playTrack(song, searchResults);
		isDropdownOpen = false;
	}

	function viewAllResults() {
		if (!searchQuery.trim()) return;
		isDropdownOpen = false;
		goto(`/songs?search=${encodeURIComponent(searchQuery.trim())}`);
	}

	function handleSearchSubmit(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			viewAllResults();
		} else if (e.key === 'Escape') {
			isDropdownOpen = false;
		}
	}

	function toggleTheme() {
		currentTheme = currentTheme === 'tunevault' ? 'dark' : 'tunevault';
		localStorage.setItem('tunevault_theme', currentTheme);
		applyTheme(currentTheme);
	}
</script>

<header
	class="glass-panel sticky top-0 z-20 flex h-[72px] items-center justify-between border-b border-[#E8E0D8] px-6 dark:border-white/10"
>
	<div class="flex items-center gap-4">
		<button
			class="btn btn-square btn-ghost text-[#2D2724] btn-sm lg:hidden dark:text-[#F9F6F2]"
			onclick={onToggleSidebar}
			aria-label="Toggle sidebar navigation"
		>
			<Menu class="h-5 w-5" />
		</button>

		<!-- Global Search Shortcut Bar with Live Dropdown -->
		<div bind:this={containerEl} class="relative w-64 md:w-80">
			<Search
				class="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-[#857D78] dark:text-[#D1C9C3]"
			/>
			<input
				bind:this={searchInputEl}
				type="text"
				bind:value={searchQuery}
				oninput={handleInput}
				onfocus={() => {
					if (searchQuery.trim()) isDropdownOpen = true;
				}}
				onkeydown={handleSearchSubmit}
				placeholder="Search tracks, artists, albums..."
				class="input w-full rounded-full border-[#E8E0D8] bg-[#F2ECE7]/80 pr-12 pl-9 text-xs font-medium text-[#2D2724] input-sm focus:border-[#C97B45] focus:bg-white dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2] dark:focus:bg-white/15"
			/>
			<kbd
				class="absolute top-1/2 right-3 kbd -translate-y-1/2 border-[#E8E0D8] bg-[#E8E0D8]/80 font-mono kbd-xs text-[10px] text-[#655E59] dark:border-white/20 dark:bg-white/15 dark:text-[#D1C9C3]"
			>
				⌘K
			</kbd>

			<!-- Live Autocomplete Dropdown Panel -->
			{#if isDropdownOpen}
				<div
					class="glass-panel absolute top-full left-0 z-50 mt-2 w-72 rounded-2xl border border-[#E8E0D8] p-2 shadow-2xl md:w-96 dark:border-white/15 dark:bg-[#1E1917]"
				>
					{#if searchLoading}
						<div class="flex items-center gap-2 p-3 text-xs text-[#857D78] dark:text-[#D1C9C3]">
							<span class="loading loading-xs loading-spinner text-[#C97B45]"></span>
							Searching catalog...
						</div>
					{:else if searchResults.length === 0}
						<div class="p-3 text-xs text-[#857D78] dark:text-[#D1C9C3]">
							No tracks found matching "{searchQuery}".
						</div>
					{:else}
						<div class="space-y-1">
							<div
								class="px-2 py-1 text-[10px] font-bold text-[#857D78] uppercase dark:text-[#D1C9C3]"
							>
								Matching Tracks ({totalResults})
							</div>
							{#each searchResults as song (song.id)}
								<button
									class="group flex w-full items-center justify-between rounded-xl p-2 text-left transition hover:bg-[#C97B45]/15 dark:hover:bg-white/10"
									onclick={() => handleSongClick(song)}
								>
									<div class="flex min-w-0 items-center gap-2.5">
										<div
											class="relative flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-[#E8E0D8] bg-[#F2ECE7] dark:border-white/10 dark:bg-white/10"
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
											<Music2 class="absolute -z-10 h-4 w-4 text-[#9A6548] dark:text-[#E58E53]" />
										</div>
										<div class="min-w-0 flex-1">
											<div
												class="truncate text-xs font-bold text-[#2D2724] group-hover:text-[#C97B45] dark:text-[#F9F6F2]"
											>
												{song.title || song.filename}
											</div>
											<div class="truncate text-[11px] text-[#857D78] dark:text-[#D1C9C3]">
												{song.artist || 'Unknown Artist'} • {song.album || 'Unknown Album'}
											</div>
										</div>
									</div>
									<div
										class="flex shrink-0 items-center gap-1 font-mono text-[10px] text-[#857D78] dark:text-[#D1C9C3]"
									>
										<span>{formatDuration(song.duration)}</span>
										<Play
											class="h-3 w-3 fill-current text-[#C97B45] opacity-0 transition-opacity group-hover:opacity-100"
										/>
									</div>
								</button>
							{/each}
						</div>

						<div class="mt-2 border-t border-[#E8E0D8] pt-2 dark:border-white/10">
							<button
								class="flex w-full items-center justify-between rounded-xl px-2 py-1.5 text-xs font-semibold text-[#C97B45] transition hover:bg-[#C97B45]/10 dark:text-[#E58E53]"
								onclick={viewAllResults}
							>
								<span>View all {totalResults} results for "{searchQuery}"</span>
								<ArrowRight class="h-3.5 w-3.5" />
							</button>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</div>

	<div class="flex items-center gap-3">
		<!-- Trigger Scan Button -->
		<button
			class="hero-gradient btn gap-2 rounded-full border-none px-4 text-xs text-white shadow-md transition btn-sm hover:opacity-90"
			onclick={onOpenScanModal}
		>
			<FolderPlus class="h-4 w-4" />
			<span class="hidden sm:inline">Start Directory Scan</span>
		</button>

		<!-- Theme Switcher -->
		<button
			class="btn btn-circle btn-ghost text-[#2D2724] btn-sm dark:text-[#F9F6F2]"
			onclick={toggleTheme}
			aria-label="Toggle theme"
		>
			{#if currentTheme === 'tunevault'}
				<Moon class="h-4 w-4" />
			{:else}
				<Sun class="h-4 w-4" />
			{/if}
		</button>
	</div>
</header>
