var getEventColor = function(data) {
    if (data.cancelled) {
        return 'red';
    } else if (data.archived) {
        return 'grey';
    }
};
$(function() {
    // page is now ready, initialize the calendar...
    $('#calendar').fullCalendar({
        themeSystem: 'bootstrap4',
        events: '/api/events/',
        editable: false,
        eventDataTransform: function(data) {
            var event = {
                id: data._id.$oid,
                title: `${data.name}  (${(data.rsvps && data.rsvps.length) || 0})`,
                start: data.date.$date,
                end: data._end_date ? data._end_date.$date : undefined,
                url: `/event/${data._id.$oid}`,
                color: getEventColor(data)
            };
            return event;
        },
        footer: {
            right: 'addNew'
        },
        customButtons: {
            addNew: {
                text: 'Add Event',
                click: function() {
                    document.location.href = "{{url_for('event_editor')}}";
                }
            }
        }
    });
});
