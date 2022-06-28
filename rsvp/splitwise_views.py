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
    # Get current user info
    resp1 = splitwise.get("/api/v3.0/get_current_user")

    # Add TOKEN USER EMAIL as friend on Splitwise
    token_user_email = os.environ.get("SPLITWISE_TOKEN_USER_EMAIL")
    data = {
        "user_email": token_user_email,
        "user_first_name": "RSVP App",
        "user_last_name": "Admin",
    }
    resp2 = splitwise.post("/api/v3.0/create_friend", data=data)

    if resp1.status_code == resp2.status_code == 200:
        # Save splitwise_id for current_user
        current_user.splitwise_id = resp1.json()["user"]["id"]
        current_user.save()
        flash(
            f"Your Splitwise ID {current_user.splitwise_id} has been saved.", "success"
        )
    else:
        print(f"Splitwise allow errors: \n{resp1.text}\n{resp2.text}")
        flash(f"Could not configure Splitwise correctly for you.", "warning")

    return redirect(session.get("next_url", url_for("index")))


@app.route("/splitwise/allow")
@login_required
def allow_splitwise():
    session["next_url"] = request.args.get("next", url_for("index"))
    return redirect(url_for("splitwise.login"))


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
        date = event.date.strftime("%Y-%m-%d")
        url = url_for("event", id=event.id, _external=True)
        data = {
            "name": f"RSVP: {event.name} ({date})",
            "whiteboard": f"{event.description}\n\n{url}",
            "group_type": "other",
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
