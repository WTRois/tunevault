import { api } from './client';

export interface IdentificationJob {
	id: number;
	job_type: 'identify';
	status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
	progress: number;
	result_json?: Record<string, unknown> | null;
	error_message?: string | null;
	created_at: string;
	completed_at?: string | null;
}

export interface IdentificationCandidate {
	id: number;
	file_id: number;
	source: string;
	score: number;
	confidence_level: 'auto_apply' | 'auto_suggest_review' | 'review_required' | 'no_match';
	status: 'pending' | 'accepted' | 'rejected' | 'expired';
	recording_mbid?: string | null;
	title?: string | null;
	artist?: string | null;
	release_title?: string | null;
}

export async function startIdentificationJob(songIds: number[]): Promise<IdentificationJob> {
	return api.post<IdentificationJob>('/identification/jobs', { song_ids: songIds });
}

export async function getIdentificationJob(jobId: number): Promise<IdentificationJob> {
	return api.get<IdentificationJob>(`/identification/jobs/${jobId}`);
}

export async function identifySong(songId: number): Promise<IdentificationJob> {
	return api.post<IdentificationJob>(`/identification/songs/${songId}/identify`);
}

export async function getSongCandidates(songId: number): Promise<IdentificationCandidate[]> {
	return api.get<IdentificationCandidate[]>(`/identification/songs/${songId}/candidates`);
}

export async function acceptCandidate(
	songId: number,
	candidateId: number
): Promise<{ accepted: boolean; file_id: number; recording_id?: number | null }> {
	return api.post(`/identification/songs/${songId}/candidates/${candidateId}/accept`);
}

export async function rejectCandidate(songId: number, candidateId: number): Promise<void> {
	return api.post(`/identification/songs/${songId}/candidates/${candidateId}/reject`);
}

export interface ReviewCandidate {
	id: number;
	file_id: number;
	filename: string;
	filepath: string;
	source: string;
	score: number;
	confidence_level: 'auto_apply' | 'auto_suggest_review' | 'review_required' | 'no_match';
	status: 'pending' | 'accepted' | 'rejected' | 'expired';
	recording_mbid?: string | null;
	title?: string | null;
	artist?: string | null;
	release_title?: string | null;
}

export interface BulkAcceptResult {
	accepted: unknown[];
	skipped: number;
	errors: string[];
}

export async function getReviewQueue(params?: {
	confidence_level?: string;
	source?: string;
	min_score?: number;
}): Promise<ReviewCandidate[]> {
	const query = new URLSearchParams();
	if (params?.confidence_level) query.set('confidence_level', params.confidence_level);
	if (params?.source) query.set('source', params.source);
	if (params?.min_score != null) query.set('min_score', String(params.min_score));
	const qs = query.toString();
	return api.get(`/identification/review${qs ? `?${qs}` : ''}`);
}

export async function bulkAccept(body: {
	candidate_ids?: number[];
	confidence_level?: string;
	min_score?: number;
}): Promise<BulkAcceptResult> {
	return api.post('/identification/review/bulk-accept', body);
}

export interface ReleasePreferences {
	preference: string;
	country: string;
	label: string;
}

export async function getReleasePreferences(): Promise<ReleasePreferences> {
	return api.get('/identification/release-preferences');
}

export async function updateReleasePreferences(
	prefs: ReleasePreferences
): Promise<ReleasePreferences> {
	return api.put('/identification/release-preferences', prefs);
}
