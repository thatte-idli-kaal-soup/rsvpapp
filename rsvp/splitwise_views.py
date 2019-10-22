import os

from flask import redirect, url_for
from flask_dance.consumer import OAuth2ConsumerBlueprint
from flask_login import current_user, login_required

from .app import app
from .models import Event, ANONYMOUS_EMAIL

splitwise_blueprint = OAuth2ConsumerBlueprint(
    "splitwise",
    __name__,
    client_id=os.environ.get("SPLITWISE_KEY"),
    client_secret=os.environ.get("SPLITWISE_SECRET"),
    base_url="https://secure.splitwise.com/",
    token_url="https://secure.splitwise.com/oauth/token",
    authorization_url="https://secure.splitwise.com/oauth/authorize",
)
app.register_blueprint(splitwise_blueprint)

splitwise = splitwise_blueprint.session


@app.route("/splitwise/allow")
@login_required
def allow_splitwise():
    if not splitwise.authorized:
        return redirect(url_for("splitwise.login"))
    resp = splitwise.get("/api/v3.0/get_current_user")
    data = resp.json()
    splitwise_id = str(data["user"]["id"])
    current_user.splitwise_id = splitwise_id
    current_user.save()
    return "Successfully obtained your Splitwise ID ({})".format(splitwise_id)


@app.route("/splitwise/create_group/<event_id>", methods=["POST"])
def create_splitwise_group(event_id):
    if not splitwise.authorized:
        return redirect(url_for("splitwise.login"))
    event = Event.objects.get(id=event_id)
    if not event.splitwise_group_id:
        data = {
            "name": event.name,
            "whiteboard": event.description,
            "group_type": "Event",
            "simplify_by_default": True,
        }
        resp = splitwise.post("/api/v3.0/create_group", data=data)
        event.splitwise_group_id = str(resp.json()["group"]["id"])
        event.save()

    for rsvp in event.active_rsvps:
        user = rsvp.user.fetch()
        if user.splitwise_id:
            data = {
                "group_id": event.splitwise_group_id,
                "user_id": user.splitwise_id,
            }
        elif user.email == ANONYMOUS_EMAIL:
            continue
        else:
            first_name, last_name = user.name.rsplit(" ", 1)
            data = {
                "group_id": event.splitwise_group_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": user.email,
            }
        resp = splitwise.post("/api/v3.0/add_user_to_group", data=data)
    return redirect(url_for("event", id=event.id))
