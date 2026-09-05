import { API_BASE_URL, api } from '$lib/api/client';

/** Real-time job progress event (blueprint §19). */
export interface JobProgressEvent {
	type: 'job.progress' | 'job.completed' | 'job.failed';
	job_id: number;
	status: string;
	completed?: number | null;
	total?: number | null;
	percent?: number | null;
	current_file?: string | null;
	error_message?: string | null;
}

/** Row shape of GET /api/jobs/{id} — the polling fallback (§19). */
interface JobRow {
	id: number;
	status: string;
	progress: number;
	error_message?: string | null;
}

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);
const POLL_INTERVAL_MS = 1500;

/**
 * Watch a job's progress: SSE first (GET /jobs/{id}/events); if the stream
 * cannot be used or drops, poll GET /jobs/{id} instead (§19 fallback).
 *
 * The watcher stops itself after a terminal event; call the returned
 * cancel function to stop early (e.g. when leaving the page).
 */
export function watchJob(
	jobId: number,
	onUpdate: (event: JobProgressEvent) => void,
	onError?: (message: string) => void
): () => void {
	let cancelled = false;
	let source: EventSource | null = null;
	let timer: ReturnType<typeof setTimeout> | null = null;

	function cancel() {
		cancelled = true;
		source?.close();
		if (timer) clearTimeout(timer);
	}

	function emit(event: JobProgressEvent) {
		if (cancelled) return;
		onUpdate(event);
		if (event.type !== 'job.progress') cancel();
	}

	function rowToEvent(row: JobRow): JobProgressEvent {
		const failed = row.status === 'failed' || row.status === 'cancelled';
		return {
			type: TERMINAL_STATUSES.has(row.status)
				? failed
					? 'job.failed'
					: 'job.completed'
				: 'job.progress',
			job_id: row.id,
			status: row.status,
			percent: row.progress,
			error_message: row.error_message ?? null
		};
	}

	function startPolling() {
		const tick = async () => {
			if (cancelled) return;
			try {
				const row = await api.get<JobRow>(`/jobs/${jobId}`);
				emit(rowToEvent(row));
				if (!cancelled && !TERMINAL_STATUSES.has(row.status)) {
					timer = setTimeout(() => void tick(), POLL_INTERVAL_MS);
				}
			} catch (err) {
				cancel();
				onError?.((err as Error).message || `Lost track of job ${jobId}`);
			}
		};
		void tick();
	}

	try {
		source = new EventSource(`${API_BASE_URL}/jobs/${jobId}/events`);
		source.onmessage = (msg) => {
			try {
				emit(JSON.parse(msg.data) as JobProgressEvent);
			} catch {
				// Ignore malformed frames — the next event still arrives.
			}
		};
		// Stream never opened or dropped mid-flight: fall back to polling.
		source.onerror = () => {
			if (cancelled) return;
			source?.close();
			source = null;
			startPolling();
		};
	} catch {
		startPolling();
	}

	return cancel;
}
