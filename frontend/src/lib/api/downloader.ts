import { api } from './client';

export interface DownloadPreviewResponse {
	url: string;
	title: string;
	artist: string;
	album?: string | null;
	duration?: number | null;
	thumbnail_url?: string | null;
	source_bitrate_estimate?: number | null;
}

export interface DownloadJobCreate {
	url: string;
	bitrate: number;
	title_override?: string;
	artist_override?: string;
	album_override?: string;
	auto_import: boolean;
}

export interface DownloadJobStatus {
	job_id: string;
	url: string;
	bitrate: number;
	status: 'pending' | 'downloading' | 'converting' | 'tagging' | 'done' | 'failed';
	progress_percent: number;
	title?: string | null;
	artist?: string | null;
	file_path?: string | null;
	imported_song_id?: number | null;
	error_message?: string | null;
	created_at: string;
	completed_at?: string | null;
}

export async function getDownloadPreview(url: string): Promise<DownloadPreviewResponse> {
	return api.post<DownloadPreviewResponse>('/download/preview', { url });
}

export async function startDownloadJob(payload: DownloadJobCreate): Promise<DownloadJobStatus> {
	return api.post<DownloadJobStatus>('/download', payload);
}

export async function getDownloadJobStatus(jobId: string): Promise<DownloadJobStatus> {
	return api.get<DownloadJobStatus>(`/download/jobs/${jobId}`);
}

export async function deleteDownloadJob(jobId: string): Promise<void> {
	return api.delete<void>(`/download/jobs/${jobId}`);
}
