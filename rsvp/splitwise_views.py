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
    get_friends,
    make_splitwise_blueprint,
    SPLITWISE_BASE_URL,
    AUTH_HEADERS,
    get_or_create_splitwise_group,
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

    get_friends(force_refresh=True)

    return redirect(session.get("next_url", url_for("index")))


@app.route("/splitwise/allow")
@login_required
def allow_splitwise():
    session["next_url"] = request.args.get("next", url_for("index"))
    return redirect(url_for("splitwise.login"))


@app.route("/splitwise/sync_group/<event_id>", methods=["POST"])
def sync_splitwise_group(event_id):
    event = Event.objects.get(id=event_id)
    users = [rsvp.user.fetch() for rsvp in event.active_rsvps]
    group = get_or_create_splitwise_group(event, users)
    if group is not None:
        sync_rsvps_with_splitwise_group(group, users)
    flash("Synced Splitwise Group for event", "success")
    return redirect(event.url)
