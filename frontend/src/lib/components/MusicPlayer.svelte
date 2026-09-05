<script lang="ts">
	import { player } from '$lib/stores/player.svelte';
	import { editModal } from '$lib/stores/editModal.svelte';
	import { API_BASE_URL } from '$lib/api/client';
	import { formatDuration } from '$lib/utils/os';
	import {
		Play,
		Pause,
		SkipBack,
		SkipForward,
		Volume2,
		VolumeX,
		Music,
		Edit3
	} from '@lucide/svelte';

	function handleSeek(e: Event) {
		const target = e.target as HTMLInputElement;
		player.seek(parseFloat(target.value));
	}

	function handleVolume(e: Event) {
		const target = e.target as HTMLInputElement;
		player.setVolume(parseFloat(target.value));
	}
</script>

<footer
	class="glass-panel sticky bottom-0 z-30 flex h-[90px] items-center justify-between border-t border-[#E8E0D8] px-6 shadow-2xl dark:border-white/10"
>
	{#if player.currentTrack}
		<!-- Left: Track info -->
		<div class="flex w-1/4 min-w-[200px] items-center gap-3">
			<button
				class="group relative flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-[#E8E0D8] shadow-md dark:border-white/10"
				onclick={() => editModal.open(player.currentTrack!.id)}
				title="Edit metadata for playing track"
				aria-label="Edit metadata for playing track"
			>
				<img
					src={`${API_BASE_URL}/songs/${player.currentTrack.id}/cover?t=${player.currentTrack.sha256}`}
					alt={player.currentTrack.title || player.currentTrack.filename}
					class="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
				/>
				<div
					class="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100"
				>
					<Edit3 class="h-4 w-4 text-white" />
				</div>
			</button>
			<div class="min-w-0 flex-1 truncate">
				<div class="flex items-center gap-1.5">
					<button
						class="max-w-full truncate text-left text-sm font-bold text-[#2D2724] hover:text-[#C97B45] dark:text-[#F9F6F2]"
						onclick={() => editModal.open(player.currentTrack!.id)}
						title="Edit metadata"
					>
						{player.currentTrack.title || player.currentTrack.filename}
					</button>
					<button
						class="btn btn-circle btn-ghost text-[#857D78] btn-xs hover:bg-[#C97B45]/15 hover:text-[#C97B45] dark:text-[#D1C9C3]"
						onclick={() => editModal.open(player.currentTrack!.id)}
						title="Edit metadata"
						aria-label="Edit metadata"
					>
						<Edit3 class="h-3.5 w-3.5" />
					</button>
				</div>
				<p class="truncate text-xs font-medium text-[#C97B45] dark:text-[#E58E53]">
					{player.currentTrack.artist || 'Unknown Artist'}
				</p>
			</div>
		</div>

		<!-- Center: Player controls & seek bar -->
		<div class="flex w-2/4 max-w-xl flex-col items-center gap-1">
			<div class="flex items-center gap-4">
				<button
					class="btn btn-circle btn-ghost text-[#857D78] btn-xs dark:text-[#D1C9C3]"
					onclick={() => player.prevTrack()}
					aria-label="Previous track"
				>
					<SkipBack class="h-4 w-4" />
				</button>

				<button
					class="hero-gradient btn btn-circle border-none text-white shadow-md transition btn-sm hover:scale-105"
					onclick={() => player.togglePlay()}
					aria-label={player.isPlaying ? 'Pause' : 'Play'}
				>
					{#if player.isPlaying}
						<Pause class="h-4 w-4 fill-current" />
					{:else}
						<Play class="ml-0.5 h-4 w-4 fill-current" />
					{/if}
				</button>

				<button
					class="btn btn-circle btn-ghost text-[#857D78] btn-xs dark:text-[#D1C9C3]"
					onclick={() => player.nextTrack()}
					aria-label="Next track"
				>
					<SkipForward class="h-4 w-4" />
				</button>
			</div>

			<div
				class="flex w-full items-center gap-2 font-mono text-[11px] text-[#857D78] dark:text-[#D1C9C3]"
			>
				<span>{formatDuration(player.currentTime)}</span>
				<input
					type="range"
					min="0"
					max={player.duration || 100}
					value={player.currentTime}
					oninput={handleSeek}
					class="player-progress range flex-1 cursor-pointer range-xs"
				/>
				<span>{formatDuration(player.duration)}</span>
			</div>
		</div>

		<!-- Right: Volume control -->
		<div class="flex w-1/4 min-w-[150px] items-center justify-end gap-2">
			<button
				class="btn btn-circle btn-ghost text-[#857D78] btn-xs dark:text-[#D1C9C3]"
				onclick={() => player.setVolume(player.volume > 0 ? 0 : 0.8)}
				aria-label="Toggle mute"
			>
				{#if player.volume === 0}
					<VolumeX class="h-4 w-4 text-error" />
				{:else}
					<Volume2 class="h-4 w-4" />
				{/if}
			</button>
			<input
				type="range"
				min="0"
				max="1"
				step="0.05"
				value={player.volume}
				oninput={handleVolume}
				class="range w-24 cursor-pointer range-xs"
			/>
		</div>
	{:else}
		<div
			class="flex w-full items-center justify-between text-xs text-[#857D78] dark:text-[#D1C9C3]"
		>
			<div class="flex items-center gap-3">
				<div
					class="flex h-10 w-10 items-center justify-center rounded-xl bg-[#F2ECE7] text-[#9A6548] dark:bg-white/10 dark:text-[#E58E53]"
				>
					<Music class="h-5 w-5" />
				</div>
				<div>
					<span class="font-bold text-[#2D2724] dark:text-[#F9F6F2]">No audio playing</span>
					<span class="block text-[11px] text-[#857D78] dark:text-[#D1C9C3]"
						>Select a track to start playback</span
					>
				</div>
			</div>
		</div>
	{/if}
</footer>

<style>
	.player-progress {
		--range-shdw: #d8a84e;
		accent-color: #d8a84e;
	}

	.player-progress::-webkit-slider-runnable-track {
		background: linear-gradient(
			to right,
			#d8a84e 0%,
			#d8a84e var(--range-progress, 0%),
			#302a35 var(--range-progress, 0%),
			#302a35 100%
		);
	}

	.player-progress::-webkit-slider-thumb {
		background: #f6d889;
		border: 2px solid #d8a84e;
	}

	.player-progress::-moz-range-progress {
		background: #d8a84e;
	}

	.player-progress::-moz-range-track {
		background: #302a35;
	}

	.player-progress::-moz-range-thumb {
		background: #f6d889;
		border: 2px solid #d8a84e;
	}
</style>
