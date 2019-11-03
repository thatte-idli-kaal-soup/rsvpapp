submit_rsvp = function(event_id) {
    $('.alert')
        .text('RSVPing...')
        .show();

    var email = $('#email').val();
    var note = $('#note').val();
    var useAnonymous = true;
    var data = { user: email, note: note, use_anonymous: useAnonymous };
    console.log(data);

    fetch(`/api/rsvps/${event_id}`, {
        credentials: 'same-origin',
        method: 'POST',
        body: JSON.stringify(data)
    })
        .then(function(response) {
            if (response.status == 200) {
                window.location.href = '';
            }
            return response.json();
        })
        .then(function(data) {
            $('.alert')
                .text(data.error)
                .show();
        });
};

delete_rsvp = function(event_id, rsvp_id) {
    $('.alert')
        .text('Un-RSVPing...')
        .show();
    fetch(`/api/rsvps/${event_id}/${rsvp_id}`, { credentials: 'same-origin', method: 'DELETE' })
        .then(function(response) {
            if (response.status == 200) {
                window.location.href = '';
            }
            return response.json();
        })
        .then(function(data) {
            $('.alert')
                .text(data.error)
                .show();
        });
};

update_message = function() {
    if ($('#name').val() !== '') {
        $('.alert')
            .text('RSVPing...')
            .show();
    }
};

update_description = function(event_id) {
    var data = {
        description: editor.codemirror.getValue()
    };
    fetch(`/api/event/${event_id}`, {
        credentials: 'same-origin',
        method: 'PATCH',
        body: JSON.stringify(data)
    })
        .then(function(response) {
            if (response.status == 200) {
                window.location.href = '';
            }
            return response.json();
        })
        .then(function(data) {
            $('.alert')
                .text(data.error)
                .show();
        });
};
