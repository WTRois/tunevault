export class ApiError extends Error {
	public status: number;
	public detail?: string | Record<string, unknown>[];

	constructor(message: string, status: number, detail?: string | Record<string, unknown>[]) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
		this.detail = detail;
	}
}

const getBaseUrl = (): string => {
	const envUrl = import.meta.env.VITE_API_BASE_URL;
	if (envUrl && envUrl.trim() !== '' && envUrl !== 'undefined') {
		const cleanUrl = envUrl.replace(/\/+$/, '');
		return cleanUrl.endsWith('/api') ? cleanUrl : `${cleanUrl}/api`;
	}

	// In browser, dynamically construct API URL to target port 8000 on the same host
	if (typeof window !== 'undefined') {
		const protocol = window.location.protocol;
		const hostname = window.location.hostname || 'localhost';
		return `${protocol}//${hostname}:8000/api`;
	}

	return 'http://localhost:8000/api';
};

export const API_BASE_URL = getBaseUrl();

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
	const url = endpoint.startsWith('http')
		? endpoint
		: `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

	const headers: Record<string, string> = {
		'Content-Type': 'application/json',
		...(options.headers as Record<string, string>)
	};

	try {
		const response = await fetch(url, {
			...options,
			headers
		});

		if (!response.ok) {
			let errorMessage = `HTTP error ${response.status}: ${response.statusText}`;
			let errorDetail: string | Record<string, unknown>[] | undefined;

			try {
				const errorData = await response.json();
				if (errorData.detail) {
					errorDetail = errorData.detail;
					errorMessage =
						typeof errorData.detail === 'string'
							? errorData.detail
							: JSON.stringify(errorData.detail);
				} else if (errorData.message) {
					errorMessage = errorData.message;
				}
			} catch {
				// Keep default status text
			}

			throw new ApiError(errorMessage, response.status, errorDetail);
		}

		if (response.status === 204) {
			return {} as T;
		}

		return (await response.json()) as T;
	} catch (error) {
		if (error instanceof ApiError) {
			throw error;
		}
		throw new ApiError((error as Error).message || 'Network request failed', 0);
	}
}

export const api = {
	get: <T>(endpoint: string, options?: RequestInit) =>
		request<T>(endpoint, { ...options, method: 'GET' }),

	post: <T>(endpoint: string, data?: unknown, options?: RequestInit) =>
		request<T>(endpoint, {
			...options,
			method: 'POST',
			body: data ? JSON.stringify(data) : undefined
		}),

	put: <T>(endpoint: string, data?: unknown, options?: RequestInit) =>
		request<T>(endpoint, {
			...options,
			method: 'PUT',
			body: data ? JSON.stringify(data) : undefined
		}),

	delete: <T>(endpoint: string, options?: RequestInit) =>
		request<T>(endpoint, { ...options, method: 'DELETE' })
};
