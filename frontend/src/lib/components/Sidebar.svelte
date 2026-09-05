<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve */
	import { page } from '$app/state';
	import favicon from '$lib/assets/favicon.svg';
	import {
		LayoutDashboard,
		Music,
		Disc,
		Users,
		Tag,
		Download,
		CloudDownload,
		Sparkles,
		FolderTree,
		Activity,
		Settings
	} from '@lucide/svelte';

	const navItems = [
		{ path: '/', label: 'Dashboard', icon: LayoutDashboard },
		{ path: '/songs', label: 'Songs', icon: Music },
		{ path: '/identify', label: 'Identify', icon: Sparkles },
		{ path: '/organize', label: 'Organize', icon: FolderTree },
		{ path: '/health', label: 'Health', icon: Activity },
		{ path: '/downloader', label: 'YT Downloader', icon: CloudDownload },
		{ path: '/albums', label: 'Albums', icon: Disc },
		{ path: '/artists', label: 'Artists', icon: Users },
		{ path: '/genres', label: 'Genres', icon: Tag },
		{ path: '/export', label: 'Export', icon: Download },
		{ path: '/settings', label: 'Settings', icon: Settings }
	];
</script>

<aside
	class="app-sidebar z-30 flex min-h-full w-72 flex-col justify-between bg-[#5B534F] p-4 text-[#F9F6F2] shadow-2xl"
>
	<div class="space-y-6">
		<!-- Branding Logo -->
		<div class="flex items-center gap-3 border-b border-white/10 px-3 py-2">
			<img src={favicon} alt="TuneVault Logo" class="h-10 w-10 shrink-0 rounded-xl shadow-lg" />
			<div>
				<h1 class="font-mono text-lg leading-none font-extrabold tracking-tight text-white">
					TuneVault
				</h1>
				<span class="font-mono text-[11px] font-medium text-[#DDD0C7]/80">Audio Indexer</span>
			</div>
		</div>

		<!-- Navigation Menu -->
		<nav class="space-y-1">
			{#each navItems as item (item.path)}
				{@const Icon = item.icon}
				<a
					href={item.path}
					class={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all ${
						page.url.pathname === item.path
							? 'bg-[#C97B45] font-semibold text-white shadow-md'
							: 'text-[#DDD0C7] hover:bg-white/10 hover:text-white'
					}`}
				>
					<Icon class="h-4 w-4 shrink-0" />
					<span>{item.label}</span>
				</a>
			{/each}
		</nav>
	</div>
</aside>
