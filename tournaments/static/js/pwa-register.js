// PWA Registration and Update Handling
class PWAManager {
    constructor() {
        this.registration = null;
        this.updateAvailable = false;
    }

    async register() {
        if (!('serviceWorker' in navigator)) {
            console.log('Service workers not supported');
            return;
        }

        try {
            this.registration = await navigator.serviceWorker.register('/sw.js', {
                scope: '/'
            });

            console.log('Service Worker registered:', this.registration);

            this.setupUpdateHandling();
            this.setupOfflineDetection();
            this.setupBackgroundSync();

        } catch (error) {
            console.error('Service Worker registration failed:', error);
        }
    }

    setupUpdateHandling() {
        // Check for updates
        this.registration.addEventListener('updatefound', () => {
            const newWorker = this.registration.installing;

            newWorker.addEventListener('statechange', () => {
                if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                    this.updateAvailable = true;
                    this.showUpdateBanner();
                }
            });
        });

        // Listen for controller change
        navigator.serviceWorker.addEventListener('controllerchange', () => {
            if (this.updateAvailable) {
                window.location.reload();
            }
        });
    }

    setupOfflineDetection() {
        window.addEventListener('online', () => {
            this.showToast('Back online! Syncing data...', 'success');
            this.syncOfflineData();
        });

        window.addEventListener('offline', () => {
            this.showToast('You are offline. Cached data available.', 'warning');
        });
    }

    setupBackgroundSync() {
        if ('SyncManager' in window) {
            navigator.serviceWorker.ready.then((registration) => {
                // Register periodic sync every hour
                if ('periodicSync' in registration) {
                    registration.periodicSync.register('update-data', {
                        minInterval: 60 * 60 * 1000 // 1 hour
                    });
                }
            });
        }
    }

    async syncOfflineData() {
        try {
            const db = await this.openDatabase();
            const pendingVotes = await this.getPendingVotes(db);

            for (const vote of pendingVotes) {
                // Sync pending votes
                await this.submitVote(vote);
                await this.removePendingVote(db, vote.id);
            }
        } catch (error) {
            console.error('Sync failed:', error);
        }
    }

    openDatabase() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open('TourneyHub', 1);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result);

            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains('pendingVotes')) {
                    db.createObjectStore('pendingVotes', {
                        keyPath: 'id',
                        autoIncrement: true
                    });
                }
            };
        });
    }

    getPendingVotes(db) {
        return new Promise((resolve, reject) => {
            const transaction = db.transaction(['pendingVotes'], 'readonly');
            const store = transaction.objectStore('pendingVotes');
            const request = store.getAll();
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    async submitVote(vote) {
        const response = await fetch(vote.url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(vote.data)
        });
        return response.json();
    }

    removePendingVote(db, id) {
        return new Promise((resolve, reject) => {
            const transaction = db.transaction(['pendingVotes'], 'readwrite');
            const store = transaction.objectStore('pendingVotes');
            store.delete(id);
            transaction.oncomplete = () => resolve();
        });
    }

    showUpdateBanner() {
        const banner = document.createElement('div');
        banner.className = 'pwa-update-banner';
        banner.innerHTML = `
            <div class="update-content">
                <span>🔄 New version available!</span>
                <button onclick="location.reload()">Update</button>
            </div>
        `;
        document.body.prepend(banner);

        // Add styles
        const style = document.createElement('style');
        style.textContent = `
            .pwa-update-banner {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                background: var(--ios-blue);
                color: white;
                z-index: 9999;
                animation: slideDown 0.3s ease;
            }
            .update-content {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 12px 16px;
                font-size: 13px;
                font-weight: 600;
            }
            .update-content button {
                background: white;
                color: var(--ios-blue);
                border: none;
                padding: 6px 14px;
                border-radius: 14px;
                font-weight: 700;
                cursor: pointer;
            }
            @keyframes slideDown {
                from { transform: translateY(-100%); }
                to { transform: translateY(0); }
            }
        `;
        document.head.appendChild(style);
    }

    showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `pwa-toast toast-${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.remove();
        }, 3000);
    }
}

// Initialize PWA
const pwa = new PWAManager();
document.addEventListener('DOMContentLoaded', () => {
    pwa.register();
});