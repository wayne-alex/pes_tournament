// Admin Service Worker for Tournament Management
const ADMIN_CACHE = 'tourney-admin-v1';
const ADMIN_DYNAMIC = 'tourney-admin-dynamic-v1';
const ADMIN_API_CACHE = 'tourney-admin-api-v1';

// Admin-specific assets to cache
const ADMIN_ASSETS = [
    '/accounts/login/',
    '/static/admin/manifest.json',
];

// Install event
self.addEventListener('install', (event) => {
    console.log('[Admin SW] Installing...');

    event.waitUntil(
        caches.open(ADMIN_CACHE)
            .then((cache) => {
                console.log('[Admin SW] Caching admin assets');
                return Promise.allSettled(
                    ADMIN_ASSETS.map(url =>
                        cache.add(url).catch(err => {
                            console.warn(`[Admin SW] Failed to cache: ${url}`, err);
                        })
                    )
                );
            })
            .then(() => self.skipWaiting())
    );
});

// Activate event
self.addEventListener('activate', (event) => {
    console.log('[Admin SW] Activating...');

    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames.map((cacheName) => {
                        if (cacheName !== ADMIN_CACHE &&
                            cacheName !== ADMIN_DYNAMIC &&
                            cacheName !== ADMIN_API_CACHE) {
                            console.log('[Admin SW] Deleting old cache:', cacheName);
                            return caches.delete(cacheName);
                        }
                    })
                );
            })
            .then(() => self.clients.claim())
    );
});

// Fetch event with admin-specific strategies
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Only handle admin scope
    if (!url.pathname.startsWith('/accounts/') &&
        !url.pathname.startsWith('/static/admin/')) {
        return;
    }

    if (request.method !== 'GET') return;

    // Admin API calls - Network only (always fresh data)
    if (url.pathname.startsWith('/admin/api/') ||
        url.pathname.includes('/admin/') && request.headers.get('Accept')?.includes('application/json')) {
        event.respondWith(networkOnly(request));
        return;
    }

    // Admin pages - Network first
    if (request.mode === 'navigate' ||
        request.headers.get('Accept')?.includes('text/html')) {
        event.respondWith(handleAdminPage(request));
        return;
    }

    // Admin static assets - Cache first
    if (url.pathname.startsWith('/static/admin/')) {
        event.respondWith(cacheFirst(request, ADMIN_CACHE));
        return;
    }

    // Default: Network first
    event.respondWith(networkFirst(request, ADMIN_DYNAMIC));
});

// Network only - for real-time admin data
async function networkOnly(request) {
    try {
        return await fetch(request);
    } catch (error) {
        return new Response(
            JSON.stringify({
                error: 'Network required for admin operations',
                requiresNetwork: true
            }),
            {
                status: 503,
                headers: { 'Content-Type': 'application/json' }
            }
        );
    }
}

// Cache first strategy
async function cacheFirst(request, cacheName) {
    const cached = await caches.match(request);
    if (cached) {
        // Background refresh
        fetch(request)
            .then(response => {
                if (response.ok) {
                    caches.open(cacheName)
                        .then(cache => cache.put(request, response));
                }
            })
            .catch(() => {});
        return cached;
    }

    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        return new Response('', { status: 404 });
    }
}

// Network first strategy
async function networkFirst(request, cacheName) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(cacheName);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        const cached = await caches.match(request);
        return cached || new Response('', { status: 404 });
    }
}

// Handle admin pages
async function handleAdminPage(request) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(ADMIN_DYNAMIC);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        const cached = await caches.match(request);
        if (cached) {
            return cached;
        }

        // Admin offline page
        return new Response(
            generateAdminOfflineHTML(),
            {
                status: 200,
                headers: { 'Content-Type': 'text/html' }
            }
        );
    }
}

// Admin offline page
function generateAdminOfflineHTML() {
    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Hub - Offline</title>
    <style>
        :root {
            --admin-bg: #1C1C1E;
            --admin-card: #2C2C2E;
            --admin-accent: #FF9F0A;
            --admin-text: #FFFFFF;
            --admin-subtext: #8E8E93;
            --admin-danger: #FF453A;
            --admin-success: #30D158;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif;
            background: var(--admin-bg);
            color: var(--admin-text);
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }
        .admin-offline-container {
            background: var(--admin-card);
            border-radius: 24px;
            padding: 40px 30px;
            max-width: 420px;
            width: 100%;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.08);
        }
        .admin-icon {
            width: 80px;
            height: 80px;
            margin: 0 auto 24px;
            background: linear-gradient(135deg, #FF9F0A, #FF6B00);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 36px;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(255, 69, 58, 0.15);
            color: var(--admin-danger);
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            margin-bottom: 20px;
        }
        .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--admin-danger);
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        .admin-title {
            font-size: 24px;
            font-weight: 900;
            margin-bottom: 4px;
        }
        .admin-subtitle {
            font-size: 12px;
            color: var(--admin-accent);
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 20px;
        }
        .admin-message {
            font-size: 14px;
            color: var(--admin-subtext);
            line-height: 1.6;
            margin-bottom: 28px;
        }
        .admin-actions {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .admin-btn {
            background: var(--admin-accent);
            color: #000;
            border: none;
            padding: 14px 24px;
            border-radius: 14px;
            font-size: 15px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
            width: 100%;
        }
        .admin-btn:active {
            opacity: 0.8;
            transform: scale(0.97);
        }
        .admin-btn.secondary {
            background: rgba(255,255,255,0.1);
            color: var(--admin-text);
        }
        .offline-notice {
            margin-top: 24px;
            padding: 14px;
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            font-size: 12px;
            color: var(--admin-subtext);
            text-align: left;
        }
        .offline-notice strong {
            color: var(--admin-text);
            display: block;
            margin-bottom: 4px;
        }
        .offline-notice ul {
            list-style: none;
            padding: 0;
            margin: 8px 0 0;
        }
        .offline-notice li {
            padding: 3px 0;
            font-size: 11px;
        }
        .offline-notice li::before {
            content: "•";
            color: var(--admin-accent);
            margin-right: 6px;
        }
    </style>
</head>
<body>
    <div class="admin-offline-container">
        <div class="admin-icon">⚙️</div>
        <div class="status-badge">
            <span class="status-dot"></span>
            <span>Admin Network Required</span>
        </div>
        <h1 class="admin-title">Admin Offline</h1>
        <p class="admin-subtitle">TOURNAMENT MANAGEMENT</p>
        <p class="admin-message">
            Network connection is required for admin operations.
            Please check your connection to continue managing tournaments.
        </p>
        
        <div class="admin-actions">
            <button class="admin-btn" onclick="location.reload()">
                Reconnect
            </button>
            <button class="admin-btn secondary" onclick="window.history.back()">
                Go Back
            </button>
        </div>
        
        <div class="offline-notice">
            <strong>⚠️ Admin Notice</strong>
            <span style="font-size:11px;">The following features require network:</span>
            <ul>
                <li>Creating/editing tournaments</li>
                <li>Updating live scores</li>
                <li>Managing teams & fixtures</li>
                <li>Real-time data sync</li>
            </ul>
        </div>
    </div>
    
    <script>
        window.addEventListener('online', () => {
            document.querySelector('.status-badge span:last-child').textContent = 'Reconnecting...';
            setTimeout(() => location.reload(), 500);
        });
    </script>
</body>
</html>`;
}

// Push notifications for admin alerts
self.addEventListener('push', (event) => {
    let data = {
        title: 'Admin Alert',
        body: 'New update in tournament management',
        icon: '/static/admin/icons/icon-192x192.png',
        badge: '/static/admin/icons/badge-72x72.png',
        tag: 'admin-notification',
        data: { url: '/admin/' },
        requireInteraction: true,
        actions: [
            { action: 'view', title: 'View' },
            { action: 'dismiss', title: 'Dismiss' }
        ]
    };

    if (event.data) {
        try {
            data = { ...data, ...JSON.parse(event.data.text()) };
        } catch (e) {
            data.body = event.data.text();
        }
    }

    event.waitUntil(
        self.registration.showNotification(data.title, {
            ...data,
            vibrate: [200, 100, 200, 100, 200],
            silent: false
        })
    );
});

// Notification click
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    if (event.action === 'dismiss') return;

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(clientList => {
                for (const client of clientList) {
                    if (client.url.includes('/admin/') && 'focus' in client) {
                        return client.focus();
                    }
                }
                if (clients.openWindow) {
                    return clients.openWindow('/admin/');
                }
            })
    );
});

// Background sync for admin operations
self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-admin-updates') {
        event.waitUntil(syncAdminUpdates());
    } else if (event.tag === 'sync-scores') {
        event.waitUntil(syncScores());
    }
});

async function syncAdminUpdates() {
    try {
        const db = await openAdminDB();
        const pendingUpdates = await getPendingUpdates(db);

        for (const update of pendingUpdates) {
            await fetch(update.url, {
                method: update.method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(update.data)
            });
            await removePendingUpdate(db, update.id);
        }
    } catch (error) {
        console.error('[Admin SW] Sync failed:', error);
    }
}

async function syncScores() {
    // Sync pending score updates
    console.log('[Admin SW] Syncing scores...');
}

// Admin IndexedDB
function openAdminDB() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open('TourneyAdmin', 1);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => resolve(request.result);

        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains('pendingUpdates')) {
                db.createObjectStore('pendingUpdates', {
                    keyPath: 'id',
                    autoIncrement: true
                });
            }
            if (!db.objectStoreNames.contains('scoreUpdates')) {
                db.createObjectStore('scoreUpdates', {
                    keyPath: 'id',
                    autoIncrement: true
                });
            }
        };
    });
}

function getPendingUpdates(db) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(['pendingUpdates'], 'readonly');
        const store = tx.objectStore('pendingUpdates');
        const request = store.getAll();
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

function removePendingUpdate(db, id) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(['pendingUpdates'], 'readwrite');
        tx.objectStore('pendingUpdates').delete(id);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
    });
}