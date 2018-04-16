import json
import os
from urllib.parse import urlparse, urlunparse

from bson.objectid import ObjectId

from flask import Flask, flash, render_template, redirect, url_for, request, send_file, session
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer import oauth_authorized
from flask_login import (
    current_user,
    fresh_login_required,
    LoginManager,
    login_required,
    login_user,
    logout_user,
)
from flaskext.versioned import Versioned
from mongoengine.errors import DoesNotExist

from models import db, Event, RSVP, User
from utils import format_date, rsvp_by

app = Flask(__name__)
app.config.from_envvar('SETTINGS')
versioned = Versioned(app)
db.init_app(app)
blueprint = make_google_blueprint(
    client_id=os.environ['GOOGLE_CLIENT_ID'],
    client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    scope=["profile", "email"],
)
app.register_blueprint(blueprint, url_prefix="/login")
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.refresh_view = "refresh"
login_manager.session_protection = "basic"
app.jinja_env.filters['format_date'] = format_date
app.jinja_env.filters['rsvp_by'] = rsvp_by
TEXT1 = app.config['TEXT1']
LOGO = app.config['LOGO']
COMPANY = app.config['COMPANY']


class DuplicateRSVPError(Exception):
    pass


@login_manager.user_loader
def load_user(user_id):
    try:
        return User.objects.get(email=user_id)

    except User.DoesNotExist:
        return


@oauth_authorized.connect_via(blueprint)
def google_logged_in(blueprint, token):
    response = google.get("/oauth2/v2/userinfo")
    info = response.json()
    email = info['email']
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        user = User(email=email, name=info['name'])
        user.save()
    # FIXME: May not be ideal, but we are trying not to annoy people!
    login_user(user, remember=True)
    return redirect(session.get('next_url', url_for('index')))


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
@login_required
def index():
    upcoming_events = Event.objects.filter(archived=False).order_by('date')
    return render_template(
        'index.html',
        upcoming_events=upcoming_events,
        TEXT1=TEXT1,
        LOGO=LOGO,
        COMPANY=COMPANY,
    )


@app.route('/archived')
@login_required
def archived():
    archived_events = Event.objects.filter(archived=True).order_by('-date')
    return render_template(
        'archived.html',
        archived_events=archived_events,
        TEXT1=TEXT1,
        LOGO=LOGO,
        COMPANY=COMPANY,
    )


@app.route('/event/<id>', methods=['GET'])
@login_required
def event(id):
    event = Event.objects(id=id).first()
    rsvps = event.rsvps
    count = len(rsvps)
    event_text = '{} - {}'.format(event['name'], format_date(event['date']))
    description = 'RSVP for {}'.format(event_text)
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
@login_required
def new(event_id):
    event = Event.objects(id=event_id).first()
    name = request.form['name']
    if event.archived:
        flash('Cannot modify an archived event!', 'warning')
    elif len(event.rsvps.filter(name=name)) > 0:
        flash('{} has already RSVP-ed!'.format(name), 'warning')
    elif name:
        rsvp_by = current_user.email if current_user.is_authenticated else None
        note = request.form['note']
        rsvp = RSVP(name=name, rsvp_by=rsvp_by, note=note)
        event.rsvps.append(rsvp)
        event.save()
    return redirect(url_for('event', id=event_id))


@app.route('/event', methods=['POST'])
@login_required
def create_event():
    date = request.form['date']
    time = request.form['time']
    item_doc = {
        'name': request.form['event-name'],
        'date': '{} {}'.format(date, time),
        'created_by': current_user.email if current_user.is_authenticated else None,
    }
    event = Event(**item_doc)
    event.save()
    return redirect(url_for('index'))


@app.route('/users', methods=['GET'])
@fresh_login_required
def users():
    users = sorted(User.objects, key=lambda u: u.name.lower())
    return render_template('users.html', TEXT1=TEXT1, LOGO=LOGO, users=users)


@app.route('/user', methods=['POST'])
@fresh_login_required
def update_user():
    email = request.form['email']
    if email != current_user.email:
        flash('You can only modify your information', 'danger')
    else:
        user = User.objects.get_or_404(email=email)
        user.upi_id = request.form['upi-id']
        user.blood_group = request.form['blood-group']
        user.save()
    return redirect(url_for('users'))


@app.route('/api/events/', methods=['GET'])
def api_events():
    return Event.objects.all().to_json()


@app.route('/api/event/<event_id>', methods=['PATCH'])
def api_event(event_id):
    try:
        doc = json.loads(request.data)
    except ValueError:
        return '{"error": "expecting JSON payload"}', 400

    allowed_fields = {'cancelled', 'archived'}
    event = Event.objects.get_or_404(id=event_id)
    for field in allowed_fields:
        if field in doc:
            setattr(event, field, doc[field])
    event.save()
    return event.to_json()


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


@app.route('/login')
def login():
    next_url = request.args.get('next', url_for('index'))
    if current_user.is_authenticated:
        return redirect(next_url)

    session['next_url'] = next_url
    return render_template(
        'login.html', TEXT1=TEXT1, LOGO=LOGO, COMPANY=COMPANY
    )


@app.route('/refresh')
def refresh():
    next_url = request.args.get('next', url_for('index'))
    session['next_url'] = next_url
    return render_template(
        'login.html', TEXT1=TEXT1, LOGO=LOGO, COMPANY=COMPANY
    )


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.jinja_env.cache = None
    app.run(host='0.0.0.0')
