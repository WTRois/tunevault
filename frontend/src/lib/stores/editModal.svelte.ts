class EditModalStore {
	songId = $state<number | null>(null);
	isOpen = $state(false);
	onSaveCallback = $state<(() => void) | null>(null);

	open(id: number, onSave?: () => void) {
		this.songId = id;
		this.isOpen = true;
		if (onSave) {
			this.onSaveCallback = onSave;
		}
	}

	close() {
		this.isOpen = false;
		this.songId = null;
		this.onSaveCallback = null;
	}

	notifySave() {
		if (this.onSaveCallback) {
			this.onSaveCallback();
		}
	}
}

export const editModal = new EditModalStore();
