// Service Worker for Tournament Hub PWA
const CACHE_NAME = 'tourney-hub-v2';
const DYNAMIC_CACHE = 'tourney-hub-dynamic-v2';
const API_CACHE = 'tourney-hub-api-v2';

// Assets to cache on install
const STATIC_ASSETS = [
    '/',
    '/static/manifest.json',
    '/static/icons/icon-72x72.png',
    '/static/icons/icon-96x96.png',
    '/static/icons/icon-128x128.png',
    '/static/icons/icon-144x144.png',
    '/static/icons/icon-152x152.png',
    '/static/icons/icon-192x192.png',
    '/static/icons/icon-384x384.png',
    '/static/icons/icon-512x512.png',
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing Service Worker...');

    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => {
                console.log('[SW] Skip waiting on install');
                return self.skipWaiting();
            })
    );
});

// Activate event - clean old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating Service Worker...');

    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames.map((cacheName) => {
                        if (cacheName !== CACHE_NAME &&
                            cacheName !== DYNAMIC_CACHE &&
                            cacheName !== API_CACHE) {
                            console.log('[SW] Deleting old cache:', cacheName);
                            return caches.delete(cacheName);
                        }
                    })
                );
            })
            .then(() => {
                console.log('[SW] Claiming clients');
                return self.clients.claim();
            })
    );
});

// Fetch event - network first with cache fallback
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // Skip non-GET requests
    if (request.method !== 'GET') return;

    // Skip chrome-extension requests
    if (url.protocol === 'chrome-extension:') return;

    // API calls - Network first with cache fallback
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(handleApiRequest(request));
        return;
    }

    // HTML pages - Network first with offline fallback
    if (request.headers.get('Accept')?.includes('text/html')) {
        event.respondWith(handleHtmlRequest(request));
        return;
    }

    // Static assets - Cache first
    if (
        url.pathname.startsWith('/static/') ||
        request.destination === 'style' ||
        request.destination === 'script' ||
        request.destination === 'image' ||
        request.destination === 'font'
    ) {
        event.respondWith(handleStaticAsset(request));
        return;
    }

    // Default: Network first with cache fallback
    event.respondWith(handleDefaultRequest(request));
});

// Handle API requests - Network first, cache for offline
async function handleApiRequest(request) {
    try {
        // Try network first
        const networkResponse = await fetch(request);

        // Cache successful responses
        if (networkResponse.ok) {
            const cache = await caches.open(API_CACHE);
            cache.put(request, networkResponse.clone());
        }

        return networkResponse;
    } catch (error) {
        // Offline - try cache
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            return cachedResponse;
        }

        // Return offline data
        return new Response(
            JSON.stringify({
                error: 'You are offline',
                offline: true,
                message: 'Data will update when connection is restored'
            }),
            {
                status: 503,
                headers: { 'Content-Type': 'application/json' }
            }
        );
    }
}

// Handle HTML requests - Network first with offline page
async function handleHtmlRequest(request) {
    try {
        const networkResponse = await fetch(request);

        if (networkResponse.ok) {
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, networkResponse.clone());
        }

        return networkResponse;
    } catch (error) {
        // Try cache first
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            return cachedResponse;
        }

        // Return offline fallback page
        const offlinePage = await caches.match('/offline/');
        if (offlinePage) {
            return offlinePage;
        }

        // Generate simple offline page
        return new Response(
            generateOfflineHTML(),
            {
                status: 200,
                headers: { 'Content-Type': 'text/html' }
            }
        );
    }
}

// Handle static assets - Cache first, network update
async function handleStaticAsset(request) {
    const cachedResponse = await caches.match(request);

    if (cachedResponse) {
        // Update cache in background
        fetch(request)
            .then((response) => {
                if (response.ok) {
                    caches.open(CACHE_NAME)
                        .then((cache) => cache.put(request, response));
                }
            })
            .catch(() => {});

        return cachedResponse;
    }

    // Not in cache - try network
    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            const cache = await caches.open(CACHE_NAME);
            cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (error) {
        return new Response('', { status: 404 });
    }
}

// Default request handler
async function handleDefaultRequest(request) {
    try {
        const networkResponse = await fetch(request);
        return networkResponse;
    } catch (error) {
        const cachedResponse = await caches.match(request);
        return cachedResponse || new Response('', { status: 404 });
    }
}

// Generate offline HTML
function generateOfflineHTML() {
    return `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tournament Hub - Offline</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif;
            background: #F2F2F7;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }
        .offline-container {
            text-align: center;
            background: white;
            border-radius: 24px;
            padding: 40px 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.08);
            max-width: 400px;
        }
        .offline-icon {
            font-size: 64px;
            margin-bottom: 20px;
        }
        .offline-title {
            font-size: 24px;
            font-weight: 900;
            color: #1C1C1E;
            margin-bottom: 10px;
        }
        .offline-message {
            font-size: 14px;
            color: #8E8E93;
            margin-bottom: 24px;
            line-height: 1.5;
        }
        .offline-btn {
            background: #007AFF;
            color: white;
            border: none;
            padding: 14px 28px;
            border-radius: 16px;
            font-size: 15px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
        }
        .offline-btn:active {
            background: #0056CC;
            transform: scale(0.96);
        }
        .cached-data {
            margin-top: 24px;
            padding: 16px;
            background: #F2F2F7;
            border-radius: 12px;
            font-size: 12px;
            color: #8E8E93;
        }
    </style>
</head>
<body>
    <div class="offline-container">
        <div class="offline-icon">📡</div>
        <h1 class="offline-title">You're Offline</h1>
        <p class="offline-message">
            Don't worry! You can still view previously loaded data.
            Updates will sync automatically when you're back online.
        </p>
        <button class="offline-btn" onclick="location.reload()">
            Try Again
        </button>
        <div class="cached-data">
            💾 Cached data is available for offline viewing
        </div>
    </div>
    
    <script>
        // Listen for online event
        window.addEventListener('online', () => {
            location.reload();
        });
        
        // Check if service worker has cached pages
        if ('caches' in window) {
            caches.keys().then(keys => {
                if (keys.length > 0) {
                    document.querySelector('.cached-data').innerHTML = 
                        '✅ ' + keys.length + ' cached page(s) available';
                }
            });
        }
    </script>
</body>
</html>`;
}

// Background sync for offline votes
self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-poll-votes') {
        event.waitUntil(syncPollVotes());
    }
});

// Sync pending poll votes
async function syncPollVotes() {
    try {
        const pendingVotes = await getPendingVotes();

        for (const vote of pendingVotes) {
            try {
                const response = await fetch(vote.url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(vote.data)
                });

                if (response.ok) {
                    await removePendingVote(vote.id);
                }
            } catch (error) {
                console.error('Failed to sync vote:', error);
            }
        }
    } catch (error) {
        console.error('Sync failed:', error);
    }
}

// IndexedDB for pending votes
function getPendingVotes() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open('TourneyHub', 1);

        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
            const db = request.result;
            const transaction = db.transaction(['pendingVotes'], 'readonly');
            const store = transaction.objectStore('pendingVotes');
            const getAll = store.getAll();
            getAll.onsuccess = () => resolve(getAll.result);
        };

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

function removePendingVote(id) {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open('TourneyHub', 1);

        request.onsuccess = () => {
            const db = request.result;
            const transaction = db.transaction(['pendingVotes'], 'readwrite');
            const store = transaction.objectStore('pendingVotes');
            store.delete(id);
            transaction.oncomplete = () => resolve();
        };
    });
}

// Push notification event
self.addEventListener('push', (event) => {
    let data = {
        title: 'Tournament Hub',
        body: 'New update available!',
        icon: '/static/icons/icon-192x192.png',
        badge: '/static/icons/badge-72x72.png',
        data: {
            url: '/'
        }
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
            body: data.body,
            icon: data.icon,
            badge: data.badge,
            data: data.data,
            actions: [
                {
                    action: 'open',
                    title: 'View'
                },
                {
                    action: 'close',
                    title: 'Dismiss'
                }
            ],
            vibrate: [200, 100, 200],
            tag: 'tournament-update'
        })
    );
});

// Notification click handler
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    if (event.action === 'close') return;

    event.waitUntil(
        clients.matchAll({ type: 'window' })
            .then((clientList) => {
                // Focus existing window if open
                for (const client of clientList) {
                    if (client.url === event.notification.data.url && 'focus' in client) {
                        return client.focus();
                    }
                }
                // Open new window
                if (clients.openWindow) {
                    return clients.openWindow(event.notification.data.url || '/');
                }
            })
    );
});