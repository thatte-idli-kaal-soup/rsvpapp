var rsvp_count = function(event) {
    if (!event.rsvps) {
        return 0;
    }
    return event.rsvps.filter(rsvp => {
        return !rsvp.cancelled && !rsvp.waitlisted;
    }).length;
};
$(function() {
    var calendarEl = document.getElementById('calendar');
    var calendar = new FullCalendar.Calendar(calendarEl, {
        plugins: ['list', 'bootstrap'],
        defaultView: 'listMonth',
        events: '/api/events/',
        themeSystem: 'bootstrap',
        timeZone: 'UTC',
        editable: false,
        noEventsMessage: 'No Events',
        contentHeight: 'auto',
        listDayAltFormat: false,
        listDayFormat: { month: 'short', year: 'numeric', day: 'numeric', weekday: 'long' },
        views: {
            listYear: { buttonText: 'Year' },
            listMonth: { buttonText: 'Month' }
        },
        customButtons: {
            addNew: {
                text: 'Add Event',
                click: function() {
                    document.location.href = '/new_event';
                }
            }
        },
        header: {
            left: 'title',
            center: '',
            right: 'prev,listMonth,listYear,next'
        },
        footer: {
            right: 'addNew'
        },
        eventDataTransform: function(data) {
            var event = {
                id: data._id.$oid,
                title: `${data.name}  (${rsvp_count(data)})`,
                start: data.date.$date,
                end: data._end_date ? data._end_date.$date : undefined,
                url: `/event/${data._id.$oid}`,
                classNames: [data.cancelled ? 'cancelled-event' : '']
            };
            return event;
        }
    });

    calendar.render();
});
