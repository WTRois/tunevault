<script lang="ts">
	import { fly, fade } from 'svelte/transition';
	import { flip } from 'svelte/animate';
	import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from '@lucide/svelte';
	import { toast, type ToastType } from '$lib/stores/toast.svelte';

	const icons: Record<ToastType, typeof CheckCircle2> = {
		success: CheckCircle2,
		error: AlertCircle,
		info: Info,
		warning: TriangleAlert
	};

	// ponytail: warna chip icon mengikuti palette warm aplikasi + aksen semantik lembut.
	const accent: Record<ToastType, string> = {
		success: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
		error: 'bg-red-500/15 text-red-600 dark:text-red-400',
		info: 'bg-sky-500/15 text-sky-600 dark:text-sky-400',
		warning: 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
	};
</script>

<div
	class="pointer-events-none fixed inset-x-0 bottom-5 z-[100] flex flex-col items-center gap-2.5 px-4"
>
	{#each toast.items as item (item.id)}
		{@const Icon = icons[item.type]}
		<div
			role="status"
			animate:flip={{ duration: 250 }}
			in:fly={{ y: 16, duration: 250 }}
			out:fade={{ duration: 200 }}
			class="toast-pill pointer-events-auto flex w-[min(30rem,calc(100vw-2rem))] items-center gap-3 rounded-full border border-[#e8e0d8] bg-[#f9f6f2]/85 py-2.5 pr-2.5 pl-3 text-sm shadow-xl shadow-black/10 backdrop-blur-xl dark:border-white/10 dark:bg-[#1e1917]/85 dark:shadow-black/40"
		>
			<span
				class={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${accent[item.type]}`}
			>
				<Icon class="h-4 w-4" />
			</span>
			<p class="flex-1 truncate font-medium text-[#2d2724] dark:text-[#f9f6f2]">{item.message}</p>
			<button
				class="btn btn-circle btn-ghost text-[#2d2724]/60 transition-colors btn-xs hover:bg-black/5 dark:text-[#f9f6f2]/60 dark:hover:bg-white/10"
				onclick={() => toast.dismiss(item.id)}
				aria-label="Dismiss notification"
			>
				<X class="h-3.5 w-3.5" />
			</button>
		</div>
	{/each}
</div>
