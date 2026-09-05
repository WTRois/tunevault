export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface ToastItem {
	id: number;
	type: ToastType;
	message: string;
	duration: number;
}

class ToastStore {
	items = $state<ToastItem[]>([]);
	private nextId = 1;

	show(message: string, type: ToastType = 'info', duration = 3500) {
		const id = this.nextId++;
		this.items = [...this.items, { id, type, message, duration }];

		if (duration > 0) {
			setTimeout(() => this.dismiss(id), duration);
		}
	}

	success(message: string, duration?: number) {
		this.show(message, 'success', duration);
	}

	error(message: string, duration?: number) {
		this.show(message, 'error', duration);
	}

	info(message: string, duration?: number) {
		this.show(message, 'info', duration);
	}

	warning(message: string, duration?: number) {
		this.show(message, 'warning', duration);
	}

	dismiss(id: number) {
		this.items = this.items.filter((item) => item.id !== id);
	}
}

export const toast = new ToastStore();
