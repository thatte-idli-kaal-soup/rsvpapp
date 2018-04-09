import datetime
import json
import os
from urllib.parse import urlparse, urlunparse

from bson.objectid import ObjectId
from flask import Flask, flash, render_template, redirect, url_for, request, send_file
from flaskext.versioned import Versioned
from mongoengine.errors import DoesNotExist

from models import Event, RSVP, db
from utils import format_date, random_id

app = Flask(__name__)
versioned = Versioned(app)
app.config['MONGODB_SETTINGS'] = {
    'host': os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/rsvpdata')
}
db.init_app(app)
TEXT1 = os.environ.get('TEXT1', "CloudYuga")
TEXT2 = os.environ.get('TEXT2', "Garage RSVP")
SECRET_KEY = os.environ.get('SECRET_KEY', 'Our awesome secret key')
app.config['SECRET_KEY'] = SECRET_KEY
LOGO = os.environ.get(
    'LOGO',
    "https://raw.githubusercontent.com/cloudyuga/rsvpapp/master/static/cloudyuga.png",
)
COMPANY = os.environ.get('COMPANY', "CloudYuga Technology Pvt. Ltd.")
app.jinja_env.filters['format_date'] = format_date


class DuplicateRSVPError(Exception):
    pass


# Views ####
@app.before_request
def redirect_heroku():
    """Redirect herokuapp requests to rsvp.thatteidlikaalsoup.team."""
    urlparts = urlparse(request.url)
    if urlparts.netloc == 'thatte-idli-rsvp.herokuapp.com':
        urlparts_list = list(urlparts)
        urlparts_list[1] = 'rsvp.thatteidlikaalsoup.team'
        return redirect(urlunparse(urlparts_list), code=301)


@app.route('/version-<version>/<path:static_file>')
def versioned_static(version, static_file):
    return send_file(static_file)


@app.route('/')
def index():
    today = datetime.date.today().strftime('%Y-%m-%d')
    upcoming_events = Event.objects.filter(date__gte=today).order_by('date')
    archived_events = Event.objects.filter(date__lt=today).order_by('-date')
    # FIXME: Run this in a cron job!
    upcoming_events.update(archived=False)
    archived_events.update(archived=True)
    count = len(upcoming_events)
    return render_template(
        'index.html',
        count=count,
        upcoming_events=upcoming_events,
        archived_events=archived_events,
        TEXT1=TEXT1,
        LOGO=LOGO,
        COMPANY=COMPANY,
    )


@app.route('/event/<id>', methods=['GET'])
def event(id):
    event = Event.objects(id=id).first()
    rsvps = event.rsvps
    count = len(rsvps)
    event_text = '{} - {}'.format(event['name'], format_date(event['date']))
    description = 'Call in for {}'.format(event_text)
    return render_template(
        'event.html',
        count=count,
        event=event,
        items=rsvps,
        TEXT1=TEXT1,
        TEXT2=event_text,
        description=description,
        LOGO=LOGO,
        COMPANY=COMPANY,
    )


@app.route('/new/<event_id>', methods=['POST'])
def new(event_id):
    event = Event.objects(id=event_id).first()
    name = request.form['name']
    if event.archived:
        flash('Cannot modify an archived event!', 'warning')
    elif len(event.rsvps.filter(name=name)) > 0:
        flash('{} has already RSVP-ed!'.format(name), 'warning')
    elif name:
        email = 'email@example.com'
        note = request.form['note']
        rsvp = RSVP(name=name, email=email, note=note)
        event.rsvps.append(rsvp)
        event.save()
    return redirect(url_for('event', id=event_id))


@app.route('/event', methods=['POST'])
def create_event():
    item_doc = {'name': request.form['name'], 'date': request.form['date']}
    event = Event(**item_doc)
    event.save()
    return redirect(url_for('index'))


# FIXME: Add POST method
@app.route('/api/events/', methods=['GET'])
def api_events():
    return Event.objects.all().to_json()


@app.route('/api/rsvps/<event_id>', methods=['GET', 'POST'])
def api_rsvps(event_id):
    event = Event.objects.get(id=event_id)
    if request.method == 'GET':
        return event.to_json()

    if event.archived:
        return json.dumps({"error": "cannot modify archived event"}), 404

    try:
        doc = json.loads(request.data)
    except ValueError:
        return '{"error": "expecting JSON payload"}', 400

    if 'name' not in doc:
        return '{"error": "name field is missing"}', 400

    if 'email' not in doc:
        return '{"error": "email field is missing"}', 400

    rsvp = RSVP(**doc)
    event.rsvps.append(rsvp)
    event.save()
    return rsvp.to_json()


@app.route('/api/rsvps/<event_id>/<rsvp_id>', methods=['GET', 'DELETE'])
def api_rsvp(event_id, rsvp_id):
    event = Event.objects.get_or_404(id=event_id)
    try:
        rsvp = event.rsvps.get(id=ObjectId(rsvp_id))
    except DoesNotExist:
        return json.dumps({"error": "not found"}), 404

    if request.method == 'GET':
        return rsvp.to_json(indent=True)

    if event.archived:
        return json.dumps({"error": "cannot modify archived event"}), 404

    if request.method == 'DELETE':
        event.rsvps.remove(rsvp)
        event.save()
        return json.dumps({"deleted": "true"})


if __name__ == '__main__':
    DEBUG = 'DEBUG' in os.environ
    if DEBUG:
        app.jinja_env.cache = None
    app.run(host='0.0.0.0', debug=DEBUG)
