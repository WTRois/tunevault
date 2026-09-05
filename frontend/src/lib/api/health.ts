import { api } from './client';

export interface LibraryHealth {
	metadata_health: number;
	identification_health: number;
	artwork_health: number;
	audio_analysis_health: number;
	duplicate_health: number;
	issues: {
		missing_artwork: number;
		unidentified: number;
		duplicates: number;
		inconsistent_album_artist: number;
		possible_upsample: number;
	};
}

export type IssueType =
	| 'missing_artwork'
	| 'unidentified'
	| 'duplicates'
	| 'inconsistent_album_artist'
	| 'possible_upsample';

export interface IssueRow {
	file_id: number;
	filename: string;
	filepath: string;
	title?: string | null;
	album?: string | null;
	expected_album_artist?: string | null;
	actual_album_artist?: string | null;
	sample_rate?: number | null;
	frequency_ceiling_hz?: number | null;
	confidence?: string | null;
}

export interface DuplicatePair {
	file_id_a: number;
	filename_a: string;
	path_a: string;
	file_id_b: number;
	filename_b: string;
	path_b: string;
	classification: string;
	similarity: number | null;
}

export async function getLibraryHealth(): Promise<LibraryHealth> {
	return api.get<LibraryHealth>('/library/health');
}

export async function getIssueRows(
	issueType: Exclude<IssueType, 'duplicates'>
): Promise<IssueRow[]> {
	return api.get<IssueRow[]>(`/library/issues/${issueType}`);
}

export async function getDuplicatePairs(): Promise<DuplicatePair[]> {
	return api.get<DuplicatePair[]>('/library/issues/duplicates');
}
