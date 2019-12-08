// Uppy setup
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
    method: 'post',
    formData: true,
    fieldName: 'photos'
});
uppy.use(Uppy.Form, {
    target: '#folder-form',
    getMetaFromForm: true,
    multipleResults: true,
    submitOnSuccess: false,
    triggerUploadOnSubmit: true
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

// Service Worker message listener
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

// Form navigation
var current_fs, next_fs; //fieldsets
$('.navigate').click(function(e) {
    e.preventDefault();
    current_fs = $(this).parents('fieldset');
    if (
        $(this)
            .attr('class')
            .indexOf('jump-existing') > -1
    ) {
        next_fs = $('#fs-existing');
    } else if (
        $(this)
            .attr('class')
            .indexOf('jump-new-dir') > -1
    ) {
        next_fs = $('#fs-new-dir');
    } else {
        next_fs = $('#fs-upload');
    }
    //show the next fieldset
    next_fs.show();
    //hide the current fieldset with style
    current_fs.hide();
});

$('#create-dir').click(function(e) {
    console.log(e.preventDefault());
    var title = $('input#title').val();
    $('.spinner-border').show();
    fetch('/share/photos/create_dir', {
        method: 'POST',
        body: JSON.stringify({ title: title }),
        headers: {
            'Content-Type': 'application/json'
            // 'Content-Type': 'application/x-www-form-urlencoded',
        },
        credentials: 'same-origin'
    })
        .then(function(response) {
            console.log(response.status);
            if (response.status != 201) {
                return response;
            }
            return response.json();
        })
        .then(function(data) {
            console.log(data);
            if (data && data.drive_id) {
                $('.spinner-border').hide();
                $('.jump-upload').click();
                $('input[name=new_dir]').val(data.drive_id);
            } else {
                $(e.target).text('Could not create directory!');
                $(e.target).addClass('btn-danger');
                $(e.target).removeClass('btn-secondary');
            }
        });
});
