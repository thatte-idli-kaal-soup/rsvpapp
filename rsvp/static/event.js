submit_rsvp = function(event_id, going) {
    if (going === undefined) {
        going = true;
    }
    $('.alert')
        .text('RSVPing...')
        .show();

    var email = $('#email').val();
    var note = $('#note').val();
    var useAnonymous = true;
    var data = { user: email, note: note, use_anonymous: useAnonymous, cancelled: !going };
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

cancel_event = function(event_id) {
    $('.alert')
        .text('Cancelling event ...')
        .show();
    fetch(`/api/event/${event_id}`, {
        method: 'PATCH',
        credentials: 'same-origin',
        body: JSON.stringify({ cancelled: true }),
        headers: { 'content-type': 'application/json' }
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

share_event = function(title) {
    var data = {
        title: title,
        text: document.getElementById('event-description').innerText + '\n\n',
        url: location.href
    };
    console.log(data);
    if (navigator.share) {
        navigator
            .share(data)
            .then(() => console.log('Successful share'))
            .catch(error => console.log('Error sharing', error));
    }
};

show_note_ui = function(element) {
    $('#note')
        .parent()
        .show();
    $(element).hide();
};

show_autocomplete_ui = function(element) {
    var autocomplete = $('#autocomplete');
    var rsvp = $('#rsvp-self');
    rsvp.hide();
    $(element).hide();
    autocomplete.show();
};

if (!navigator.share) {
    $('#share-event').hide();
    $('#copy-event').show();
} else {
    $('#share-event').show();
    $('#copy-event').hide();
}

var options = {
    search: function(searchTerm) {
        var re = new RegExp(searchTerm, 'iu');
        $('#email').val(searchTerm);
        return window.users.filter(function(user) {
            return re.exec(user.name) || re.exec(user.nick) || re.exec(user.email);
        });
    },
    getResultValue: function(user) {
        return user.nick || user.name;
    },
    onSubmit: function(user) {
        console.log(user);
        $('#email').val(user.email);
    }
};
new Autocomplete('#autocomplete', options);
