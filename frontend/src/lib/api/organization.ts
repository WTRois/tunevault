import { api } from './client';

export interface OrganizationPlan {
	file_id: number;
	old_path?: string;
	new_path?: string;
	metadata_changes?: Record<string, [unknown, unknown]> | null;
	artwork?: unknown;
	confidence?: number;
	dry_run?: boolean;
	skipped?: string;
	error?: string;
}

/** A plan without `skipped`/`error` — carries the full §15 fields. */
export type ActionablePlan = OrganizationPlan & { old_path: string; new_path: string };

export function isActionable(plan: OrganizationPlan): plan is ActionablePlan {
	return !plan.skipped && !plan.error;
}

export interface PreviewResponse {
	plans: OrganizationPlan[];
	dry_run: boolean;
}

export interface ApplyResponse {
	change_set_id: number;
	name: string;
	job_id: number;
	dry_run: boolean;
	queued_files: number;
}

export interface UndoResponse {
	change_set_id: number;
	job_id: number;
}

export interface ChangeSetSummary {
	id: number;
	name: string;
	status: string;
	created_by: string;
	created_at: string;
	applied_at?: string | null;
	rolled_back_at?: string | null;
}

export interface OrganizeJob {
	id: number;
	job_type: string;
	status: string;
	progress: number;
	result_json?: Record<string, unknown> | null;
	error_message?: string | null;
	created_at: string;
	completed_at?: string | null;
}

export interface PreviewOptions {
	all?: boolean;
	song_ids?: number[];
	file_ids?: number[];
}

export async function preview(options: PreviewOptions): Promise<PreviewResponse> {
	return api.post<PreviewResponse>('/organization/preview', options);
}

export async function applyPlans(
	options: PreviewOptions & { name?: string }
): Promise<ApplyResponse> {
	return api.post<ApplyResponse>('/organization/apply', options);
}

export async function undoChangeSet(changeSetId: number): Promise<UndoResponse> {
	return api.post<UndoResponse>(`/organization/undo/${changeSetId}`);
}

export async function listChangeSets(): Promise<ChangeSetSummary[]> {
	return api.get<ChangeSetSummary[]>('/change-sets');
}

export async function getOrganizeJob(jobId: number): Promise<OrganizeJob> {
	return api.get<OrganizeJob>(`/organization/jobs/${jobId}`);
}
