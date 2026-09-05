<script lang="ts">
	import { onMount } from 'svelte';
	import { getDefaultMusicDirectory } from '$lib/utils/os';
	import { api } from '$lib/api/client';
	import { toast } from '$lib/stores/toast.svelte';

	let defaultScanPath = $state('');

	onMount(() => {
		defaultScanPath = localStorage.getItem('tunevault_default_path') || getDefaultMusicDirectory();
	});

	function saveSettings() {
		localStorage.setItem('tunevault_default_path', defaultScanPath);
		toast.success('Settings saved successfully.');
	}

	async function triggerRescan() {
		if (!confirm(`Trigger re-scan on default directory "${defaultScanPath}"?`)) return;
		try {
			await api.post('/scan', { directory_path: defaultScanPath, perform_audio_analysis: true });
			toast.success('Re-scan job started successfully!');
		} catch (err) {
			toast.error((err as Error).message || 'Failed to start scan');
		}
	}
</script>

<div class="mx-auto max-w-3xl space-y-6">
	<div>
		<h1 class="text-3xl font-extrabold tracking-tight text-[#2D2724] dark:text-[#F9F6F2]">
			Settings
		</h1>
		<p class="text-sm font-medium text-[#655E59] dark:text-[#D1C9C3]">
			TuneVault system configuration & preferences
		</p>
	</div>

	<!-- Directory Preferences Card -->
	<div class="glass-panel space-y-4 rounded-3xl p-6">
		<h2 class="text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">Default Scanner Path</h2>

		<div>
			<label for="settings-scan-path" class="label">
				<span class="label-text text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]"
					>Default Music Folder Path</span
				>
			</label>
			<input
				id="settings-scan-path"
				type="text"
				bind:value={defaultScanPath}
				placeholder="/music or C:\Users\..."
				class="input-bordered input w-full border-[#E8E0D8] bg-white/80 font-mono text-xs text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
			/>
			<span class="mt-1 block text-xs font-medium text-[#655E59] dark:text-[#D1C9C3]">
				This path is used as the default target whenever triggering directory scans.
			</span>
		</div>

		<div class="flex items-center gap-3 pt-2">
			<button
				class="hero-gradient btn rounded-full border-none px-5 text-xs text-white shadow-md"
				onclick={saveSettings}>Save Settings</button
			>
			<button
				class="btn rounded-full border-[#E8E0D8] btn-outline text-xs text-[#2D2724] dark:border-white/20 dark:text-[#F9F6F2]"
				onclick={triggerRescan}>Re-index Library</button
			>
		</div>
	</div>

	<!-- System Information Card -->
	<div class="glass-panel space-y-3 rounded-3xl p-6">
		<h2 class="text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">System Information</h2>
		<div
			class="grid grid-cols-2 gap-2 rounded-2xl bg-[#F2ECE7] p-4 font-mono text-xs text-[#2D2724] dark:bg-white/10 dark:text-[#F9F6F2]"
		>
			<div><span class="font-bold text-[#5B534F] dark:text-[#D1C9C3]">App:</span> TuneVault</div>
			<div><span class="font-bold text-[#5B534F] dark:text-[#D1C9C3]">Version:</span> v1.0.0</div>
			<div>
				<span class="font-bold text-[#5B534F] dark:text-[#D1C9C3]">Frontend:</span> SvelteKit + DaisyUI
				v5
			</div>
			<div>
				<span class="font-bold text-[#5B534F] dark:text-[#D1C9C3]">Backend:</span> FastAPI + SQLModel
			</div>
			<div>
				<span class="font-bold text-[#5B534F] dark:text-[#D1C9C3]">Database:</span> SQLite (WAL mode)
			</div>
			<div>
				<span class="font-bold text-[#5B534F] dark:text-[#D1C9C3]">Audio Engine:</span> Mutagen & Librosa
			</div>
		</div>
	</div>
</div>
