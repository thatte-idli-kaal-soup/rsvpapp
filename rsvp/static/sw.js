self.addEventListener('install', event => {
    console.log('👷', 'install', event);
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    console.log('👷', 'activate', event);
    return self.clients.claim();
});

self.addEventListener('fetch', function(event) {
    if (event.request.method !== 'POST') return;
    if (event.request.url.endsWith('/share') === false) return;

    // Redirect to the form page
    event.respondWith(Response.redirect('/share/photos'));

    // Send a message to the web js with the file information
    event.waitUntil(
        (async function() {
            const data = await event.request.formData();
            const client = await self.clients.get(event.resultingClientId || event.clientId);
            const files = data.getAll('photos');
            client.postMessage({ files, action: 'upload-photos' });
        })()
    );
});
