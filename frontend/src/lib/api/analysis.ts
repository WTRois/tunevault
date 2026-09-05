import { api } from './client';

export interface TechnicalInfo {
	container: string | null;
	codec: string | null;
	bitrate: number | null;
	sample_rate: number | null;
	bit_depth: number | null;
	channels: number | null;
	channel_layout: string | null;
	duration_ms: number | null;
	lossless: boolean | null;
}

export interface AudioFeatures {
	bpm: number | null;
	musical_key: string | null;
	integrated_lufs: number | null;
	true_peak_db: number | null;
	replaygain_track_db: number | null;
	replaygain_album_db: number | null;
	dynamic_range: number | null;
	spectral_centroid: number | null;
	frequency_ceiling_hz: number | null;
}

export interface UpsampleVerdict {
	status: 'normal' | 'possible_upsample' | 'insufficient_data';
	confidence: string | null;
}

export interface AudioAnalysis {
	file_id: number;
	analyzed: boolean;
	technical: TechnicalInfo;
	features: AudioFeatures | null;
	upsample: UpsampleVerdict | null;
	analysis_version: string | null;
	analyzed_at: string | null;
}

export interface JobInfo {
	id: number;
	job_type: string;
	status: string;
	progress: number;
	result_json?: Record<string, unknown> | null;
	error_message?: string | null;
	created_at: string;
	completed_at?: string | null;
}

export async function getFileAnalysis(fileId: number): Promise<AudioAnalysis> {
	return api.get<AudioAnalysis>(`/files/${fileId}/analysis`);
}

export async function startAnalysis(
	fileId: number
): Promise<{ file_id: number; job_id: number; status: string }> {
	return api.post(`/files/${fileId}/analysis`);
}

export async function getJob(jobId: number): Promise<JobInfo> {
	return api.get<JobInfo>(`/jobs/${jobId}`);
}
