import copy
import json
from urllib.parse import urlparse, urlunparse

from bson.objectid import ObjectId
from flask import flash, render_template, redirect, url_for, request, send_file, session
from flask_login import (
    current_user, fresh_login_required, login_required, logout_user
)
from mongoengine.errors import DoesNotExist

from .models import Event, RSVP, User
from .utils import format_date, generate_password, role_required
from . import app


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


# Views ####
@app.route('/')
@login_required
def index():
    upcoming_events = Event.objects.filter(archived=False).order_by('date')
    return render_template('index.html', upcoming_events=upcoming_events)


@app.route('/archived')
@login_required
def archived():
    archived_events = Event.objects.filter(archived=True).order_by('-date')
    return render_template('archived.html', archived_events=archived_events)


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
        TEXT2=event_text,
        description=description,
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
    role = request.values.get('role')
    if role:
        users = User.objects(roles__in=[role])
    else:
        users = User.objects(email__ne=current_user.email)
    users = sorted(users, key=lambda u: u.name.lower())
    return render_template('users.html', users=users, role=role)


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
        user.nick = request.form['nick']
        user.dob = request.form['dob'] or None
        user.save()
        flash('Successfully updated your information', 'info')
    return redirect(url_for('users'))


@app.route('/approve_user/<email>', methods=['GET'])
@role_required('admin')
def approve_user(email):
    user = User.objects.get_or_404(email=email)
    if not user.has_role('.approved-user'):
        user.update(push__roles='.approved-user')
    return redirect(url_for('users'))


@app.route('/approve_users/', methods=['GET'])
@role_required('admin')
def approve_users():
    users = sorted(
        User.objects(roles__nin=['.approved-user']),
        key=lambda u: u.name.lower(),
    )
    return render_template('approve_users.html', users=users)


@app.route('/social', methods=['GET'])
@fresh_login_required
def social():
    social = copy.deepcopy(app.config['SOCIAL'])
    if current_user.has_any_role('admin', 'social-admin'):
        for platform in social:
            if not platform['type'] == 'account':
                continue

            platform['password'] = generate_password(platform, app.secret_key)
    return render_template('social.html', social=social)


# API ####
@app.route('/api/events/', methods=['GET'])
@login_required
def api_events():
    return Event.objects.all().to_json()


@app.route('/api/event/<event_id>', methods=['PATCH'])
@login_required
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
@login_required
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
@login_required
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


# Login/Logout ####
@app.route('/login')
def login():
    next_url = request.args.get('next', url_for('index'))
    if current_user.is_authenticated:
        return redirect(next_url)

    session['next_url'] = next_url
    return render_template('login.html')


@app.route('/refresh')
def refresh():
    next_url = request.args.get('next', url_for('index'))
    session['next_url'] = next_url
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/approval_awaited/<name>')
def approval_awaited(name):
    return render_template('approval_awaited.html', name=name)
