<script lang="ts">
	import './layout.css';
	import favicon from '$lib/assets/favicon.svg';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import Header from '$lib/components/Header.svelte';
	import RightSidebar from '$lib/components/RightSidebar.svelte';
	import MusicPlayer from '$lib/components/MusicPlayer.svelte';
	import EditSongModal from '$lib/components/EditSongModal.svelte';
	import Toast from '$lib/components/Toast.svelte';

	let { children } = $props();

	let mobileSidebarOpen = $state(false);

	function toggleMobileSidebar() {
		mobileSidebarOpen = !mobileSidebarOpen;
	}

	function openScanModal() {
		const modal = document.getElementById('scan-modal') as HTMLDialogElement;
		modal?.showModal();
	}
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>TuneVault — Audio Archive</title>
</svelte:head>

<div class="app-background flex min-h-screen flex-col font-sans text-[#2D2724]">
	<!-- Floating application shell -->
	<div class="app-shell flex flex-1 overflow-hidden">
		<!-- Desktop Sidebar Navigation -->
		<div class="hidden shrink-0 lg:block">
			<Sidebar />
		</div>

		<!-- Mobile Drawer Navigation -->
		{#if mobileSidebarOpen}
			<div class="fixed inset-0 z-50 flex lg:hidden">
				<button
					class="fixed inset-0 bg-black/50 backdrop-blur-sm"
					onclick={toggleMobileSidebar}
					aria-label="Close sidebar"
				></button>
				<div class="relative z-10">
					<Sidebar />
				</div>
			</div>
		{/if}

		<!-- Center + Right Area -->
		<div class="app-main-panel flex min-w-0 flex-1 flex-col">
			<!-- Header Bar (72px) -->
			<Header onToggleSidebar={toggleMobileSidebar} onOpenScanModal={openScanModal} />

			<!-- Content Area + Right Sidebar -->
			<div class="flex flex-1 overflow-hidden">
				<!-- Main Content Scroll Area -->
				<main class="app-content flex-1 space-y-6 overflow-y-auto p-4 md:p-8">
					{@render children()}
				</main>

				<!-- Track Inspector Right Sidebar (300px) -->
				<RightSidebar />
			</div>
		</div>
	</div>

	<!-- Persistent Sticky Music Player Bar (90px) -->
	<MusicPlayer />

	<!-- Global Edit Metadata Modal -->
	<EditSongModal />
	<Toast />
</div>
