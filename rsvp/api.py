import datetime
import json

from bson.objectid import ObjectId
from flask import request, jsonify, flash
from flask_login import current_user, login_required
from mongoengine.errors import DoesNotExist

from .models import Event, Post, RSVP, User, ANONYMOUS_EMAIL
from . import app


@app.route("/api/events/", methods=["GET"])
@login_required
def api_events():
    start = request.values.get("start")
    end = request.values.get("end")
    events = Event.objects
    if start:
        events = events.filter(date__gte=start)
    if end:
        events = events.filter(date__lte=end)
    return jsonify(json.loads(events.to_json()))


def event_to_attendance(event, user):
    attended = event.rsvps.filter(user=user, cancelled=False, waitlisted=False).count()
    return {
        "year": event.date.year,
        "month": event.date.strftime("%m-%b"),
        "weekday": event.date.strftime("%w-%A"),
        "attended": attended,
    }


@app.route("/api/attendance", methods=["GET"])
@login_required
def api_attendance():
    events = Event.objects.filter(cancelled=False)
    data = [event_to_attendance(event, current_user) for event in events]
    return jsonify(data)


@app.route("/api/event/<event_id>", methods=["PATCH"])
@login_required
def api_event(event_id):
    try:
        doc = json.loads(request.data)
    except ValueError:
        return '{"error": "expecting JSON payload"}', 400

    allowed_fields = {"cancelled", "archived", "description"}
    event = Event.objects.get_or_404(id=event_id)
    for field in allowed_fields:
        if field in doc:
            setattr(event, field, doc[field])
    event.save()
    event.update_waitlist()
    return event.to_json()


@app.route("/api/rsvps/<event_id>", methods=["GET", "POST"])
@login_required
def api_rsvps(event_id):
    event = Event.objects.get(id=event_id)
    if request.method == "GET":
        event_json = json.loads(event.to_json(use_db_field=False))
        for i, rsvp in enumerate(event.rsvps):
            event_json["rsvps"][i]["user"] = json.loads(rsvp.user.fetch().to_json())
        return json.dumps(event_json)

    if not event.can_rsvp(current_user):
        return json.dumps({"error": "cannot modify event"}), 404

    try:
        doc = json.loads(request.data)
    except ValueError:
        return '{"error": "expecting JSON payload"}', 400

    if "user" not in doc:
        return '{"error": "user field is missing"}', 400

    use_anonymous = doc.pop("use_anonymous", False)
    try:
        user = User.objects.get(email=doc["user"])
    except User.DoesNotExist:
        if event.is_paid:
            return ('{"error": "Only registered users can RSVP on paid events"}', 400)
        elif use_anonymous:
            user = User.objects.get(email=ANONYMOUS_EMAIL)
        else:
            return '{"error": "user does not exist"}', 400

    if event.is_paid and not (user.splitwise_connected and user.acceptable_dues):
        return (
            '{"error": "Users without Splitwise linked or with dues above the limit cannot RSVP."}',
            400,
        )

    new_rsvp = (user.email == ANONYMOUS_EMAIL) or Event.objects.filter(
        id=event.id, rsvps__user=user
    ).count() == 0

    if new_rsvp:
        data = {
            "rsvp_by": current_user.email
            if current_user.is_authenticated
            else ANONYMOUS_EMAIL,
            "user": user.email,
        }
        data.update(doc)
        if user.email == ANONYMOUS_EMAIL:
            data["note"] = (
                "{user} ({note})".format(**data) if data["note"] else data["user"]
            )
            data["user"] = user.email
        rsvp = RSVP(**data)
        if not (rsvp.user.fetch().email == ANONYMOUS_EMAIL and rsvp.cancelled):
            event.update(push__rsvps=rsvp)
    else:
        rsvp = event.rsvps.get(user=user)
        if "note" in doc:
            rsvp.note = doc["note"]
        # Update the timestamp if a cancelled RSVP is being updated, adding
        # notes to an existing RSVP should not change the timestamp.
        if rsvp.cancelled:
            rsvp.date = datetime.datetime.now()
        rsvp.cancelled = doc.get("cancelled", False)

    event.save()
    event.update_waitlist()
    if not event.sync_rsvps_with_splitwise():
        flash("Could not find Splitwise group to sync RSVPs with.", "warning")
    return rsvp.to_json()


@app.route("/api/rsvps/<event_id>/<rsvp_id>", methods=["GET", "DELETE"])
@login_required
def api_rsvp(event_id, rsvp_id):
    event = Event.objects.get_or_404(id=event_id)
    try:
        rsvp = event.rsvps.get(id=ObjectId(rsvp_id))
    except DoesNotExist:
        return json.dumps({"error": "not found"}), 404

    if request.method == "GET":
        return rsvp.to_json(indent=True)

    if not event.can_rsvp(current_user):
        return json.dumps({"error": "cannot modify event"}), 404

    if rsvp.user.fetch().email == ANONYMOUS_EMAIL:
        event.update(pull__rsvps=rsvp)
    else:
        rsvp.cancelled = True
    event.save()
    event.update_waitlist()
    if not event.sync_rsvps_with_splitwise():
        flash("Could not find Splitwise group to sync RSVPs with.", "warning")
    return json.dumps({"deleted": "true"})


@app.route("/api/users/", methods=["GET"])
@login_required
def api_users():
    return User.approved_users().to_json()


@app.route("/api/posts/", methods=["GET"])
def api_posts():
    all_posts = bool(request.values.get("all", False))
    if current_user.is_authenticated and all_posts:
        posts = Post.published_posts()
    else:
        posts = Post.public_posts()
    data = json.loads(posts.to_json())
    return jsonify(data)
