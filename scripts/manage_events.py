import datetime
import os
import sys

import click
import mongoengine.errors

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import Event
from rsvp import app
from utils import format_date


@click.group()
def cli():
    """A CLI to manage events"""
    pass


@click.command()
def archive_events():
    """Archive old events."""
    click.echo('Archiving events...')
    with app.test_request_context():
        today = datetime.datetime.now()
        upcoming_events = Event.objects.filter(date__gte=today).order_by(
            'date'
        )
        archived_events = Event.objects.filter(date__lt=today).order_by(
            '-date'
        )
        upcoming_events.update(archived=False)
        archived_events.update(archived=True)


@click.command()
@click.argument('event_id', type=str)
def cancel_event(event_id):
    """Cancel the specified event."""
    try:
        event = Event.objects.get(id=event_id)
    except (
        mongoengine.errors.ValidationError, mongoengine.errors.DoesNotExist
    ):
        click.echo('Could not find the specified event')
    else:
        click.echo('Cancelling event {}'.format(event.id))
        confirmation = click.confirm(
            'Are you sure you want to cancel the event - {} - {}'.format(
                event.name, format_date(event.date)
            )
        )
        if confirmation:
            event.cancelled = True
            event.save()


cli.add_command(archive_events)
cli.add_command(cancel_event)
if __name__ == '__main__':
    cli()
