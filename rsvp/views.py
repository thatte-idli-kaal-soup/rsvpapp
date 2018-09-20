import copy
from datetime import datetime
import json
import os
import re
from urllib.parse import urlparse, urlunparse

from bson.objectid import ObjectId
from flask import (
    flash,
    render_template,
    redirect,
    url_for,
    request,
    send_file,
    session,
    make_response,
)
from flask_login import (
    current_user, fresh_login_required, login_required, logout_user
)
from mongoengine.errors import DoesNotExist

from .models import Event, Post, RSVP, User, ANONYMOUS_EMAIL
from .utils import (
    format_date,
    generate_password,
    get_attendance,
    role_required,
    send_approved_email,
)
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
    event_text = '{} - {}'.format(event['name'], format_date(event['date']))
    description = 'RSVP for {}'.format(event_text)
    approved_users = User.approved_users()
    return render_template(
        'event.html',
        count=event.rsvp_count,
        event=event,
        items=event.rsvps,
        active_rsvps=event.active_rsvps,
        approved_users=approved_users,
        TEXT2=event_text,
        description=description,
    )


@app.route('/new/<event_id>', methods=['POST'])
@login_required
def new_rsvp(event_id):
    event = Event.objects(id=event_id).first()
    email = request.form['email'].strip()
    note = request.form['note'].strip()
    try:
        print('Trying to fetch user with email {}'.format(repr(email)))
        user = User.objects.get(email=email)
    except DoesNotExist:
        flash(
            'Could not find user with email, using anonymous user!', 'warning'
        )
        user = User.objects.get(email=ANONYMOUS_EMAIL)
        note = '{}: {}'.format(email, note) if note else email
    if not current_user.is_admin and event.archived:
        flash('Cannot modify an archived event!', 'warning')
    elif len(event.active_rsvps.filter(user=user)) > 0:
        flash('{} has already RSVP-ed!'.format(email), 'warning')
    elif len(event.rsvps.filter(user=user)) > 0:
        rsvp = event.rsvps.get(user=user)
        rsvp.cancelled = False
        rsvp.note = note
        rsvp.save()
    elif email:
        rsvp_by = current_user.email if current_user.is_authenticated else None
        rsvp = RSVP(user=user, rsvp_by=rsvp_by, note=note)
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
        'description': request.form.get('event-description', ''),
    }
    event = Event(**item_doc)
    event.save()
    return redirect(url_for('index'))


@app.route('/users', methods=['GET'])
@fresh_login_required
def users():
    role = request.values.get('role')
    gender = request.values.get('gender')
    users = User.approved_users()
    if role:
        users = users.filter(roles__in=[role])
    if gender:
        users = users.filter(gender=None if gender == 'unknown' else gender)
    roles = sorted(
        {
            role
            for user in User.objects.all()
            for role in user.roles
            if not role.startswith('.')
        }
    )
    genders = set(filter(None, User.objects.values_list('gender'))).union(
        {'unknown'}
    )
    users = sorted(users, key=lambda u: u.name.lower())
    return render_template(
        'users.html',
        users=users,
        gender=gender,
        genders=genders,
        roles=roles,
        role=role,
    )


@app.route('/user', methods=['POST'])
@fresh_login_required
def update_user():
    email = request.form['email']
    if email != current_user.email:
        flash('You can only modify your information', 'danger')
    else:
        user = User.objects.get_or_404(email=email)
        user.upi_id = request.form['upi-id'].strip()
        user.blood_group = request.form['blood-group'].strip()
        user.nick = request.form['nick'].strip()
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
        send_approved_email(user)
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

            platform['password'] = generate_password(
                platform['name'], app.secret_key
            )
    return render_template('social.html', social=social)


# API ####
@app.route('/api/events/', methods=['GET'])
@login_required
def api_events():
    start = request.values.get('start')
    end = request.values.get('end')
    events = Event.objects
    if start:
        events = events.filter(date__gte=start)
    if end:
        events = events.filter(date__lte=end)
    return events.to_json()


@app.route('/api/event/<event_id>', methods=['PATCH'])
@login_required
def api_event(event_id):
    try:
        doc = json.loads(request.data)
    except ValueError:
        return '{"error": "expecting JSON payload"}', 400

    allowed_fields = {'cancelled', 'archived', 'description'}
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
        event_json = json.loads(event.to_json(use_db_field=False))
        for i, rsvp in enumerate(event.rsvps):
            event_json['rsvps'][i]['user'] = json.loads(
                rsvp.user.fetch().to_json()
            )
        return json.dumps(event_json)

    if not current_user.is_admin and event.archived:
        return json.dumps({"error": "cannot modify archived event"}), 404

    try:
        doc = json.loads(request.data)
    except ValueError:
        return '{"error": "expecting JSON payload"}', 400

    if 'user' not in doc:
        return '{"error": "user field is missing"}', 400

    else:
        try:
            user = User.objects.get(email=doc['user'])
        except User.DoesNotExist:
            return '{"error": "user does not exist"}', 400

    try:
        rsvp = event.rsvps.get(user=user)
        if 'note' in doc:
            rsvp.note = doc['note']
        rsvp.cancelled = False
        rsvp.save()
    except DoesNotExist:
        data = {
            'rsvp_by': current_user.email if current_user.is_authenticated else ANONYMOUS_EMAIL
        }
        data.update(doc)
        rsvp = RSVP(**data)
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

    if not current_user.is_admin and event.archived:
        return json.dumps({"error": "cannot modify archived event"}), 404

    if request.method == 'DELETE':
        if rsvp.user.fetch().email == ANONYMOUS_EMAIL:
            event.rsvps.remove(rsvp)
            event.save()
        else:
            rsvp.cancelled = True
            rsvp.save()
        return json.dumps({"deleted": "true"})


@app.route('/api/users/', methods=['GET'])
@login_required
def api_users():
    return User.approved_users().to_json()


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


@app.route('/onesta/<letters>')
@login_required
def onesta(letters):
    letters = letters.lower()
    users = [user for user in User.objects if letters in user.name.lower()]
    return render_template('names.html', users=users)


@app.route('/attendance', methods=['GET', 'POST'])
@role_required('admin')
def attendance():
    if request.method == 'GET':
        return render_template('attendance.html')

    start = request.form.get('start-date')
    end = request.form.get('end-date')
    events = Event.objects.filter(date__gte=start, date__lte=end)
    response = make_response(get_attendance(events))
    response.headers[
        "Content-Disposition"
    ] = "attachment; filename=attendance-{}--{}.csv".format(
        start, end
    )
    response.headers["Content-type"] = "text/csv"
    return response


@app.route('/posts')
@login_required
def show_posts():
    posts = Post.objects.order_by('-created_at')
    return render_template('posts.html', posts=posts)
