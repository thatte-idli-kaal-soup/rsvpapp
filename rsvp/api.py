import json

from bson.objectid import ObjectId
from flask import request
from flask_login import current_user, login_required
from mongoengine.errors import DoesNotExist

from .models import Event, RSVP, User, ANONYMOUS_EMAIL
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
    return events.to_json()


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
    return event.to_json()


@app.route("/api/rsvps/<event_id>", methods=["GET", "POST"])
@login_required
def api_rsvps(event_id):
    event = Event.objects.get(id=event_id)
    if request.method == "GET":
        event_json = json.loads(event.to_json(use_db_field=False))
        for i, rsvp in enumerate(event.rsvps):
            event_json["rsvps"][i]["user"] = json.loads(
                rsvp.user.fetch().to_json()
            )
        return json.dumps(event_json)

    if not current_user.is_admin and event.archived:
        return json.dumps({"error": "cannot modify archived event"}), 404

    try:
        doc = json.loads(request.data)
    except ValueError:
        return '{"error": "expecting JSON payload"}', 400

    if "user" not in doc:
        return '{"error": "user field is missing"}', 400

    else:
        try:
            user = User.objects.get(email=doc["user"])
        except User.DoesNotExist:
            return '{"error": "user does not exist"}', 400

    try:
        rsvp = event.rsvps.get(user=user)
        if "note" in doc:
            rsvp.note = doc["note"]
        rsvp.cancelled = False
        rsvp.save()
    except DoesNotExist:
        data = {
            "rsvp_by": current_user.email
            if current_user.is_authenticated
            else ANONYMOUS_EMAIL
        }
        data.update(doc)
        rsvp = RSVP(**data)
        event.rsvps.append(rsvp)
    event.save()
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

    if not current_user.is_admin and event.archived:
        return json.dumps({"error": "cannot modify archived event"}), 404

    if request.method == "DELETE":
        if rsvp.user.fetch().email == ANONYMOUS_EMAIL:
            event.rsvps.remove(rsvp)
            event.save()
        else:
            rsvp.cancelled = True
            rsvp.save()
        return json.dumps({"deleted": "true"})


@app.route("/api/users/", methods=["GET"])
@login_required
def api_users():
    return User.approved_users().to_json()