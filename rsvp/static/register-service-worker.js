if ('serviceWorker' in navigator) {
    navigator.serviceWorker
        .register('/sw.js')
        .then(function(reg) {
            console.log('Service worker registered.');
        })
        .catch(function(err) {
            console.log('Service worker not registered. This happened:', err);
        });
}
