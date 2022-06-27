from functools import partial
import os

from flask import redirect, url_for, _app_ctx_stack as stack, flash, request, session
from flask_dance.consumer import oauth_authorized
from flask.globals import LocalProxy, _lookup_app_object
from flask_login import current_user, login_required
import requests

from .app import app
from .models import Event, ANONYMOUS_EMAIL, User
from .splitwise_utils import (
    make_splitwise_blueprint,
    SPLITWISE_BASE_URL,
    AUTH_HEADERS,
    sync_rsvps_with_splitwise_group,
)


splitwise = LocalProxy(partial(_lookup_app_object, "splitwise_oauth"))
splitwise_blueprint = make_splitwise_blueprint(
    client_id=os.environ.get("SPLITWISE_KEY"),
    client_secret=os.environ.get("SPLITWISE_SECRET"),
)
app.register_blueprint(splitwise_blueprint)


@oauth_authorized.connect_via(splitwise_blueprint)
def splitwise_authorized(blueprint, token):
    return redirect(session.get("next_url", url_for("index")))


@app.route("/splitwise/allow")
@login_required
def allow_splitwise():
    next_url = request.args.get("next", url_for("index"))
    if not splitwise.authorized:
        session["next_url"] = next_url
        return redirect(url_for("splitwise.login"))

    # Save splitwise_id for current_user
    resp = splitwise.get("/api/v3.0/get_current_user")
    data = resp.json()
    splitwise_id = data["user"]["id"]
    current_user.splitwise_id = splitwise_id
    current_user.save()

    # Add TOKEN USER EMAIL as friend on Splitwise
    token_user_email = os.environ.get("SPLITWISE_TOKEN_USER_EMAIL")
    data = {
        "user_email": token_user_email,
        "user_first_name": "RSVP App",
        "user_last_name": "Admin",
    }
    resp = splitwise.post("/api/v3.0/create_friend", data=data)
    assert resp.status_code == 200, "Could not add TOKEN USER EMAIL as friend."
    flash(f"Your Splitwise ID {current_user.splitwise_id} has been saved.", "success")
    return redirect(next_url)


@app.route("/splitwise/sync_group/<event_id>", methods=["POST"])
def sync_splitwise_group(event_id):
    event = Event.objects.get(id=event_id)
    event_url = url_for("event", id=event.id)

    users = [rsvp.user.fetch() for rsvp in event.active_rsvps]
    if not all(user.splitwise_id for user in users):
        missing_nicks = [user.nick_name for user in users if not user.splitwise_id]
        flash(
            f"Cannot create Splitwise group since some users do not have Splitwise IDs: "
            f"{', '.join(missing_nicks)}",
            "danger",
        )
        return redirect(event_url)

    group = None
    # Try to get the Splitwise Group
    if event.splitwise_group_id:
        # NOTE: Ideally, we'd like to update group title/description but
        # Splitwise API doesn't seem to have an end-point for that?!
        # FIXME: Should we switch to using get_groups() with a force update on
        # the cached group information? But, then we'd probably want to call
        # the function even when a new group is created for predictability.
        get_url = f"{SPLITWISE_BASE_URL}/api/v3.0/get_group/{event.splitwise_group_id}"
        data = requests.get(get_url, headers=AUTH_HEADERS).json()
        group = data.get("group")
        error = data.get("errors", {}).get("base", [""])[0]
        deleted_error = "Invalid API Request: record not found"
        if group is None and error != deleted_error:
            flash(f"Could not sync with Splitwise. Failure: {data}", "danger")
            return redirect(event_url)

        elif group is None:
            print(f"Group {event.splitwise_group_id} seems to be deleted")

        else:
            print(f"Found Splitwise group {event.splitwise_group_id}")

    # Create a new Splitwise Group, if required
    if group is None:
        data = {
            "name": event.name,
            "whiteboard": f"{event.description}\n\n{event_url}",
            "group_type": "Event",
            "simplify_by_default": True,
        }
        users_data = {
            f"user__{i}__id": user.splitwise_id for i, user in enumerate(users)
        }
        data.update(users_data)
        create_url = f"{SPLITWISE_BASE_URL}/api/v3.0/create_group"
        data = requests.post(create_url, data=data, headers=AUTH_HEADERS).json()
        group = data["group"]
        event.splitwise_group_id = group["id"]
        event.save()
        flash("Created Splitwise Group for event", "success")

    sync_rsvps_with_splitwise_group(group, users)

    flash("Synced Splitwise Group for event", "success")
    return redirect(event_url)
