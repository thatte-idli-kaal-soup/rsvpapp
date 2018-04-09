import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rsvp import app
from models import Event

with app.test_request_context():
    today = datetime.datetime.now()
    upcoming_events = Event.objects.filter(date__gte=today).order_by('date')
    archived_events = Event.objects.filter(date__lt=today).order_by('-date')
    upcoming_events.update(archived=False)
    archived_events.update(archived=True)
