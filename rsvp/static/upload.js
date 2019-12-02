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
