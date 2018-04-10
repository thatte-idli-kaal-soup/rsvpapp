import json
import os
from urllib.parse import urlparse, urlunparse

from bson.objectid import ObjectId

from flask import Flask, flash, render_template, redirect, url_for, request, send_file, session
from flask_login import LoginManager, login_required, login_user, logout_user, current_user
from flaskext.versioned import Versioned
from mongoengine.errors import DoesNotExist
from requests.exceptions import HTTPError

from auth import Auth, get_google_auth
from models import db, Event, RSVP, User
from utils import format_date

app = Flask(__name__)
app.config.from_envvar('SETTINGS')
versioned = Versioned(app)
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.session_protection = "strong"
app.jinja_env.filters['format_date'] = format_date
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
        email = current_user.email if hasattr(
            current_user, 'email'
        ) else 'anonymous@user.com'
        note = request.form['note']
        rsvp = RSVP(name=name, email=email, note=note)
        event.rsvps.append(rsvp)
        event.save()
    return redirect(url_for('event', id=event_id))


@app.route('/event', methods=['POST'])
@login_required
def create_event():
    date = request.form['date']
    time = request.form['time']
    item_doc = {
        'name': request.form['event-name'], 'date': '{} {}'.format(date, time)
    }
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


@app.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    google = get_google_auth(
        redirect_uri=url_for(
            'callback', _external=True, next=request.args.get('next')
        )
    )
    auth_url, state = google.authorization_url(
        Auth.AUTH_URI, access_type='offline', next=request.args.get('next')
    )
    session['oauth_state'] = state
    return render_template(
        'login.html',
        auth_url=auth_url,
        TEXT1=TEXT1,
        LOGO=LOGO,
        COMPANY=COMPANY,
    )


@app.route('/oauth2callback')
def callback():
    if current_user is not None and current_user.is_authenticated:
        return redirect(request.args.get('next', url_for('index')))

    if 'error' in request.args:
        if request.args.get('error') == 'access_denied':
            return 'You denied access.'

        return 'Error encountered.'

    if 'code' not in request.args and 'state' not in request.args:
        return redirect(url_for('login'), next=request.args.get('next'))

    else:
        google = get_google_auth(
            state=session['oauth_state'],
            redirect_uri=url_for(
                'callback', _external=True, next=request.args.get('next')
            ),
        )
        try:
            token = google.fetch_token(
                Auth.TOKEN_URI,
                client_secret=Auth.CLIENT_SECRET,
                authorization_response=request.url,
            )
        except HTTPError:
            return 'HTTPError occurred.'

        google = get_google_auth(
            token=token,
            redirect_uri=url_for(
                'callback', _external=True, next=request.args.get('next')
            ),
        )
        resp = google.get(Auth.USER_INFO)
        if resp.status_code == 200:
            user_data = resp.json()
            email = user_data['email']
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                user = User(email)
            user.set_tokens(json.dumps(token))
            user.name = user_data['name']
            user.save()
            login_user(user)
            return redirect(request.args.get('next', url_for('index')))

        return 'Could not fetch your information.'


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.jinja_env.cache = None
    app.run(host='0.0.0.0')
