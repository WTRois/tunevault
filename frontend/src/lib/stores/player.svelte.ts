import { API_BASE_URL } from '$lib/api/client';

export interface Track {
	id: number;
	title?: string;
	artist?: string;
	album?: string;
	duration?: number;
	filename: string;
	sha256: string;
}

class PlayerStore {
	currentTrack = $state<Track | null>(null);
	isPlaying = $state(false);
	currentTime = $state(0);
	duration = $state(0);
	volume = $state(0.8);
	queue = $state<Track[]>([]);
	currentIndex = $state(-1);

	private audioElement: HTMLAudioElement | null = null;
	private targetVolume = 0.8;
	private fadeAnimationId: number | null = null;

	constructor() {
		if (typeof window !== 'undefined') {
			this.audioElement = new Audio();

			this.audioElement.addEventListener('timeupdate', () => {
				if (this.audioElement) {
					this.currentTime = this.audioElement.currentTime;
				}
			});

			this.audioElement.addEventListener('loadedmetadata', () => {
				if (this.audioElement) {
					this.duration = this.audioElement.duration || this.currentTrack?.duration || 0;
				}
			});

			this.audioElement.addEventListener('ended', () => {
				this.nextTrack();
			});
		}
	}

	/**
	 * Linear Volume Fade Ramping Engine (Default 350ms transition)
	 */
	private fadeVolume(targetVol: number, durationMs = 350): Promise<void> {
		return new Promise((resolve) => {
			if (!this.audioElement) return resolve();

			if (this.fadeAnimationId !== null) {
				cancelAnimationFrame(this.fadeAnimationId);
				this.fadeAnimationId = null;
			}

			const startVol = this.audioElement.volume;
			const startTime = performance.now();

			const step = (now: number) => {
				if (!this.audioElement) return resolve();

				const elapsed = now - startTime;
				const progress = Math.min(elapsed / durationMs, 1);
				this.audioElement.volume = Math.max(
					0,
					Math.min(1, startVol + (targetVol - startVol) * progress)
				);

				if (progress < 1) {
					this.fadeAnimationId = requestAnimationFrame(step);
				} else {
					this.fadeAnimationId = null;
					resolve();
				}
			};

			this.fadeAnimationId = requestAnimationFrame(step);
		});
	}

	updateTrack(track: Track) {
		this.currentTrack = { ...track };
		this.queue = this.queue.map((queuedTrack) =>
			queuedTrack.id === track.id ? { ...queuedTrack, ...track } : queuedTrack
		);
	}

	setQueue(tracks: Track[], startTrack?: Track) {
		this.queue = tracks;
		if (startTrack) {
			const idx = tracks.findIndex((t) => t.id === startTrack.id);
			this.currentIndex = idx !== -1 ? idx : 0;
		}
	}

	async playTrack(track: Track, newQueue?: Track[]) {
		if (!this.audioElement) return;

		if (newQueue && newQueue.length > 0) {
			this.setQueue(newQueue, track);
		} else if (this.queue.length === 0) {
			this.setQueue([track], track);
		} else {
			const idx = this.queue.findIndex((t) => t.id === track.id);
			if (idx !== -1) this.currentIndex = idx;
		}

		// Smooth Fade Out current audio if already playing
		if (this.isPlaying) {
			await this.fadeVolume(0, 200);
		}

		this.currentTrack = track;
		this.audioElement.src = `${API_BASE_URL}/songs/${track.id}/stream`;
		this.audioElement.volume = 0;

		try {
			await this.audioElement.play();
			this.isPlaying = true;
			// Smooth Fade In to target user volume
			await this.fadeVolume(this.targetVolume, 350);
		} catch (err) {
			console.error('Audio playback failed:', err);
			this.isPlaying = false;
		}
	}

	async togglePlay() {
		if (!this.audioElement || !this.currentTrack) return;

		if (this.isPlaying) {
			// Smooth Fade Out before pause
			await this.fadeVolume(0, 300);
			this.audioElement.pause();
			this.isPlaying = false;
		} else {
			this.audioElement.volume = 0;
			try {
				await this.audioElement.play();
				this.isPlaying = true;
				// Smooth Fade In after play
				await this.fadeVolume(this.targetVolume, 350);
			} catch (err) {
				console.error('Failed to resume playback:', err);
			}
		}
	}

	async nextTrack() {
		if (this.queue.length === 0 || this.currentIndex === -1) return;
		const nextIndex = (this.currentIndex + 1) % this.queue.length;
		await this.playTrack(this.queue[nextIndex]);
	}

	async prevTrack() {
		if (this.queue.length === 0 || this.currentIndex === -1) return;
		const prevIndex = (this.currentIndex - 1 + this.queue.length) % this.queue.length;
		await this.playTrack(this.queue[prevIndex]);
	}

	seek(seconds: number) {
		if (!this.audioElement) return;
		this.audioElement.currentTime = seconds;
		this.currentTime = seconds;
	}

	setVolume(val: number) {
		const newVol = Math.max(0, Math.min(1, val));
		this.volume = newVol;
		this.targetVolume = newVol;
		if (this.audioElement && this.fadeAnimationId === null) {
			this.audioElement.volume = newVol;
		}
	}
}

export const player = new PlayerStore();
