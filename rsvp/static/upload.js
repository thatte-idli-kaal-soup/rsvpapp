var uppy = Uppy.Core({ autoProceed: false, id: 'photos', allowMultipleUploads: false });
uppy.use(Uppy.Dashboard, {
    target: '#drag-drop-area',
    inline: true,
    hideUploadButton: true,
    note:
        'This will upload files to the shared Google Drive. Please select an existing folder or provide a new folder name',
    proudlyDisplayPoweredByUppy: false
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
