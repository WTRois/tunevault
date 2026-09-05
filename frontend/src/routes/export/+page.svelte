<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve */
	/* eslint-disable svelte/prefer-svelte-reactivity */
	import { FileJson, FileSpreadsheet, FileText } from '@lucide/svelte';

	let exportSearch = $state('');
	let exportGenre = $state('');

	function getExportUrl(format: 'json' | 'csv' | 'xlsx'): string {
		const params = new URLSearchParams();
		if (exportSearch) params.set('search', exportSearch);
		if (exportGenre) params.set('genre', exportGenre);
		const queryString = params.toString();
		return `/api/export/${format}${queryString ? `?${queryString}` : ''}`;
	}
</script>

<div class="mx-auto max-w-4xl space-y-6">
	<div>
		<h1 class="text-3xl font-extrabold tracking-tight text-[#2D2724] dark:text-[#F9F6F2]">
			Export Metadata
		</h1>
		<p class="text-sm font-medium text-[#655E59] dark:text-[#D1C9C3]">
			Export your indexed audio metadata into multiple formats
		</p>
	</div>

	<!-- Optional Export Filter Options -->
	<div class="glass-panel space-y-4 rounded-3xl p-6">
		<h2 class="text-lg font-bold text-[#2D2724] dark:text-[#F9F6F2]">
			Filter Export Data (Optional)
		</h2>

		<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
			<div>
				<label for="export-search" class="label">
					<span class="label-text text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]"
						>Filter by Keyword</span
					>
				</label>
				<input
					id="export-search"
					type="text"
					bind:value={exportSearch}
					placeholder="Artist, Album, Title..."
					class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-sm text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
				/>
			</div>

			<div>
				<label for="export-genre" class="label">
					<span class="label-text text-xs font-bold text-[#2D2724] dark:text-[#F9F6F2]"
						>Filter by Genre</span
					>
				</label>
				<input
					id="export-genre"
					type="text"
					bind:value={exportGenre}
					placeholder="Rock, Jazz, Pop..."
					class="input-bordered input w-full border-[#E8E0D8] bg-white/80 text-sm text-[#2D2724] dark:border-white/20 dark:bg-white/10 dark:text-[#F9F6F2]"
				/>
			</div>
		</div>
	</div>

	<!-- Download Format Options -->
	<div class="grid grid-cols-1 gap-4 md:grid-cols-3">
		<!-- JSON Card -->
		<div
			class="glass-card flex flex-col items-center justify-between space-y-4 rounded-3xl p-6 text-center"
		>
			<div class="mb-2 rounded-2xl bg-[#C97B45]/15 p-4 text-[#C97B45]">
				<FileJson class="h-8 w-8" />
			</div>
			<div>
				<h3 class="text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">JSON Format</h3>
				<p class="mt-1 text-xs text-[#857D78] dark:text-[#D1C9C3]">
					Structured JSON data format suitable for web apps & integrations.
				</p>
			</div>
			<a
				href={getExportUrl('json')}
				download
				class="hero-gradient btn w-full rounded-full border-none text-white shadow-md"
			>
				Download .json
			</a>
		</div>

		<!-- CSV Card -->
		<div
			class="glass-card flex flex-col items-center justify-between space-y-4 rounded-3xl p-6 text-center"
		>
			<div class="mb-2 rounded-2xl bg-[#8E9570]/20 p-4 text-[#8E9570]">
				<FileText class="h-8 w-8" />
			</div>
			<div>
				<h3 class="text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">CSV Format</h3>
				<p class="mt-1 text-xs text-[#857D78] dark:text-[#D1C9C3]">
					Standard Comma-Separated Values file for spreadsheets.
				</p>
			</div>
			<a
				href={getExportUrl('csv')}
				download
				class="btn w-full rounded-full border-none bg-[#8E9570] text-white shadow-md hover:bg-[#8E9570]/90"
			>
				Download .csv
			</a>
		</div>

		<!-- Excel XLSX Card -->
		<div
			class="glass-card flex flex-col items-center justify-between space-y-4 rounded-3xl p-6 text-center"
		>
			<div class="mb-2 rounded-2xl bg-[#9A6548]/20 p-4 text-[#9A6548]">
				<FileSpreadsheet class="h-8 w-8" />
			</div>
			<div>
				<h3 class="text-lg font-extrabold text-[#2D2724] dark:text-[#F9F6F2]">Excel (.xlsx)</h3>
				<p class="mt-1 text-xs text-[#857D78] dark:text-[#D1C9C3]">
					Microsoft Excel Workbook format with headers & columns.
				</p>
			</div>
			<a
				href={getExportUrl('xlsx')}
				download
				class="btn w-full rounded-full border-none bg-[#9A6548] text-white shadow-md hover:bg-[#9A6548]/90"
			>
				Download .xlsx
			</a>
		</div>
	</div>
</div>
