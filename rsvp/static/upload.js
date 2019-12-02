var uppy = Uppy.Core({ autoProceed: false, id: 'photos', allowMultipleUploads: false });
uppy.use(Uppy.Dashboard, {
    target: '#drag-drop-area',
    inline: true,
    hideUploadButton: true,
    proudlyDisplayPoweredByUppy: false,
    width: '100%'
});
uppy.use(Uppy.XHRUpload, {
    endpoint: '/share/photos/upload',
    formData: true,
    fieldName: 'photos',
    bundle: true
});
uppy.use(Uppy.Form, {
    target: '#folder-form',
    getMetaFromForm: true,
    multipleResults: false,
    submitOnSuccess: false,
    triggerUploadOnSubmit: true
});

navigator.serviceWorker.addEventListener('message', event => {
    if (event.data.action !== 'upload-photos') return;
    console.log(event.data.files, event.data.action);
    event.data.files.map(file => {
        uppy.addFile({
            name: file.name,
            type: file.type,
            data: file,
            source: 'Local',
            isRemote: false
        });
    });
});

uppy.on('complete', result => {
    console.log('successful files:', result.successful);
    if (result.successful.length > 0) {
        var driveURL = result.successful[0].response.body.drive_url;
        window.location.href = driveURL;
    }
});

uppy.on('error', error => {
    console.log(error);
    uppy.info(JSON.parse(error.request.response).error, 'error', 5000);
});
