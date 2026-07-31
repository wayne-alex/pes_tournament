// Admin PWA Registration
class AdminPWAManager {
    constructor() {
        this.registration = null;
        this.isOnline = navigator.onLine;
        this.pendingOperations = [];
    }

    async register() {
        if (!('serviceWorker' in navigator)) {
            console.warn('[Admin PWA] Service workers not supported');
            this.showNotification('Service workers not supported', 'warning');
            return;
        }

        // Check if user is authenticated for admin
        if (!this.isAdminAuthenticated()) {
            console.log('[Admin PWA] Not authenticated for admin');
            return;
        }

        try {
            this.registration = await navigator.serviceWorker.register(
                '/static/admin/admin-sw.js',
                { scope: '/accounts/' }
            );

            console.log('[Admin PWA] Service Worker registered');

            this.setupEventListeners();
            this.setupPeriodicSync();
            this.checkForUpdates();

        } catch (error) {
            console.error('[Admin PWA] Registration failed:', error);
            this.showNotification('Could not enable offline features', 'error');
        }
    }

    isAdminAuthenticated() {
        // Check if user is on admin page and has admin cookies/tokens
        const isAdminPage = window.location.pathname.startsWith('/admin/');
        const hasAdminCookie = document.cookie.includes('admin') ||
                               document.cookie.includes('sessionid');
        return isAdminPage && hasAdminCookie;
    }

    setupEventListeners() {
        // Online/offline detection
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.showNotification('Back online - syncing data', 'success');
            this.syncPendingOperations();
        });

        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.showNotification('Offline - changes will sync later', 'warning');
        });

        // Listen for messages from service worker
        navigator.serviceWorker.addEventListener('message', (event) => {
            if (event.data.type === 'SYNC_COMPLETE') {
                this.showNotification('Data synced successfully', 'success');
            }
        });

        // Before unload, warn about pending changes
        window.addEventListener('beforeunload', (e) => {
            if (this.pendingOperations.length > 0) {
                e.preventDefault();
                e.returnValue = 'You have unsaved changes that will sync when online.';
            }
        });
    }

    async setupPeriodicSync() {
        if (!this.registration) return;

        try {
            // Request periodic background sync (every 30 minutes)
            if ('periodicSync' in this.registration) {
                const status = await navigator.permissions.query({
                    name: 'periodic-background-sync',
                });

                if (status.state === 'granted') {
                    await this.registration.periodicSync.register('sync-admin-updates', {
                        minInterval: 30 * 60 * 1000, // 30 minutes
                    });
                    console.log('[Admin PWA] Periodic sync registered');
                }
            }
        } catch (error) {
            console.warn('[Admin PWA] Periodic sync not available:', error);
        }
    }

    async checkForUpdates() {
        if (!this.registration) return;

        // Check every 5 minutes
        setInterval(() => {
            this.registration.update();
        }, 5 * 60 * 1000);

        this.registration.addEventListener('updatefound', () => {
            const newWorker = this.registration.installing;

            newWorker.addEventListener('statechange', () => {
                if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                    this.showUpdatePrompt();
                }
            });
        });
    }

    showUpdatePrompt() {
        const prompt = document.createElement('div');
        prompt.className = 'admin-update-prompt';
        prompt.innerHTML = `
            <div class="admin-update-content">
                <div>
                    <strong>Update Available</strong>
                    <p>New admin features ready</p>
                </div>
                <button class="update-btn" onclick="window.location.reload()">
                    Update Now
                </button>
            </div>
        `;
        prompt.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: #2C2C2E;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 16px;
            padding: 16px 20px;
            color: white;
            z-index: 99999;
            box-shadow: 0 8px 32px rgba(0,0,0,0.4);
            animation: slideUp 0.3s ease;
            max-width: 320px;
        `;

        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideUp {
                from { transform: translateY(100px); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
            }
            .admin-update-content {
                display: flex;
                align-items: center;
                gap: 16px;
            }
            .admin-update-content strong {
                font-size: 13px;
                display: block;
                margin-bottom: 2px;
            }
            .admin-update-content p {
                font-size: 11px;
                color: #8E8E93;
                margin: 0;
            }
            .update-btn {
                background: #FF9F0A;
                color: #000;
                border: none;
                padding: 8px 16px;
                border-radius: 10px;
                font-weight: 700;
                font-size: 12px;
                cursor: pointer;
                white-space: nowrap;
            }
        `;
        document.head.appendChild(style);
        document.body.appendChild(prompt);
    }

    async queueOperation(operation) {
        if (!this.isOnline) {
            this.pendingOperations.push({
                ...operation,
                timestamp: Date.now()
            });
            this.showNotification('Queued for sync', 'info');
            await this.saveToIndexedDB(operation);
            return { queued: true };
        }
        return { queued: false };
    }

    async syncPendingOperations() {
        const db = await this.openDatabase();
        const pending = await this.getPendingOperations(db);

        for (const op of pending) {
            try {
                const response = await fetch(op.url, {
                    method: op.method,
                    headers: op.headers || {},
                    body: op.data ? JSON.stringify(op.data) : undefined
                });

                if (response.ok) {
                    await this.removeOperation(db, op.id);
                }
            } catch (error) {
                console.error('[Admin PWA] Sync failed for:', op, error);
            }
        }

        this.pendingOperations = [];
        this.showNotification('All changes synced', 'success');
    }

    openDatabase() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open('TourneyAdmin', 1);
            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result);
            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                if (!db.objectStoreNames.contains('pendingOperations')) {
                    db.createObjectStore('pendingOperations', {
                        keyPath: 'id',
                        autoIncrement: true
                    });
                }
            };
        });
    }

    getPendingOperations(db) {
        return new Promise((resolve, reject) => {
            const tx = db.transaction(['pendingOperations'], 'readonly');
            const request = tx.objectStore('pendingOperations').getAll();
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
    }

    removeOperation(db, id) {
        return new Promise((resolve, reject) => {
            const tx = db.transaction(['pendingOperations'], 'readwrite');
            tx.objectStore('pendingOperations').delete(id);
            tx.oncomplete = () => resolve();
            tx.onerror = () => reject(tx.error);
        });
    }

    saveToIndexedDB(operation) {
        return new Promise((resolve, reject) => {
            this.openDatabase().then(db => {
                const tx = db.transaction(['pendingOperations'], 'readwrite');
                tx.objectStore('pendingOperations').add(operation);
                tx.oncomplete = () => resolve();
                tx.onerror = () => reject(tx.error);
            });
        });
    }

    showNotification(message, type = 'info') {
        // Use the admin notification system if available
        if (window.showAdminToast) {
            window.showAdminToast(message, type);
            return;
        }

        // Fallback toast
        const toast = document.createElement('div');
        const colors = {
            success: '#30D158',
            warning: '#FF9F0A',
            error: '#FF453A',
            info: '#0A84FF'
        };

        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: ${colors[type] || colors.info};
            color: ${type === 'warning' ? '#000' : '#FFF'};
            padding: 12px 20px;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 700;
            z-index: 99999;
            animation: adminSlideIn 0.3s ease;
            box-shadow: 0 4px 16px rgba(0,0,0,0.3);
        `;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s';
            setTimeout(() => toast.remove(), 300);
        }, 3000);

        const style = document.createElement('style');
        style.textContent = `
            @keyframes adminSlideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
        `;
        document.head.appendChild(style);
    }
}

// Initialize admin PWA
const adminPWA = new AdminPWAManager();

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => adminPWA.register());
} else {
    adminPWA.register();
}

// Export globally
window.adminPWA = adminPWA;