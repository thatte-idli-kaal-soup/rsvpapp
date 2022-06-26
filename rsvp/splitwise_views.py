from functools import partial
import os

from flask import redirect, url_for, _app_ctx_stack as stack, flash, request, session
from flask_dance.consumer import OAuth2ConsumerBlueprint, oauth_authorized
from flask_login import current_user, login_required
from flask.globals import LocalProxy, _lookup_app_object
from oauthlib.oauth2 import WebApplicationClient, BackendApplicationClient
import requests

from .app import app
from .models import Event, ANONYMOUS_EMAIL, User

SPLITWISE_BASE_URL = "https://secure.splitwise.com/"


class HybridClient(WebApplicationClient):
    """Override grant type on WebApplicationClient.

    Splitwise expects client_credentials grant_type, but WebApplicationClient
    has application_code grant_type.

    """

    grant_type = BackendApplicationClient.grant_type


def make_splitwise_blueprint(client_id=None, client_secret=None):
    client = HybridClient(client_id, token=None)
    splitwise_bp = OAuth2ConsumerBlueprint(
        "splitwise",
        __name__,
        client_id=client_id,
        client_secret=client_secret,
        client=client,
        base_url=SPLITWISE_BASE_URL,
        token_url=f"{SPLITWISE_BASE_URL}/oauth/token",
        authorization_url=f"{SPLITWISE_BASE_URL}/oauth/authorize",
        # NOTE: Hack to include the argument to OAuth2Session().fetch_token
        token_url_params={"include_client_id": True},
    )

    @splitwise_bp.before_app_request
    def set_applocal_session():
        ctx = stack.top
        ctx.splitwise_oauth = splitwise_bp.session

    return splitwise_bp


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
    splitwise_id = str(data["user"]["id"])
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
    token = os.environ.get("SPLITWISE_TOKEN")
    token_user = os.environ.get("SPLITWISE_TOKEN_USER_ID")
    headers = {"Authorization": f"Bearer {token}"}
    event = Event.objects.get(id=event_id)
    event_url = url_for("event", id=event.id)

    users = [rsvp.user.fetch() for rsvp in event.active_rsvps]
    if not all(user.splitwise_id for user in users):
        missing_nicks = [
            (user.nick or user.name) for user in users if not user.splitwise_id
        ]
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
        get_url = f"{SPLITWISE_BASE_URL}/api/v3.0/get_group/{event.splitwise_group_id}"
        data = requests.get(get_url, headers=headers).json()
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
        data = requests.post(create_url, data=data, headers=headers).json()
        group = data["group"]
        event.splitwise_group_id = str(group["id"])
        event.save()
        flash("Created Splitwise Group for event", "success")

    # Add all currently active RSVP users to the Splitwise group
    members = {str(member["id"]) for member in group.get("members", [])}
    for user in users:
        if user.splitwise_id in members:
            continue
        data = {
            "group_id": event.splitwise_group_id,
            "user_id": user.splitwise_id,
        }
        response = requests.post(
            f"{SPLITWISE_BASE_URL}/api/v3.0/add_user_to_group",
            data=data,
            headers=headers,
        )
        failure_msg = f"Failed adding user {user.email} -- {user.splitwise_id}"
        assert response.status_code == 200, f"{failure_msg}: {response}"
        errors = response.json().get("errors")
        assert not errors, f"{failure_msg}: {response.json()}"

    # Remove all users who are don't have active RSVPs
    user_splitwise_ids = {user.splitwise_id for user in users}
    for member in members:
        # Don't remove TOKEN admin user, since we use that account to
        # manage groups. Also, don't remove active RSVP users
        if member == token_user or member in user_splitwise_ids:
            continue
        data = {
            "group_id": event.splitwise_group_id,
            "user_id": member,
        }
        response = requests.post(
            f"{SPLITWISE_BASE_URL}/api/v3.0/remove_user_from_group",
            data=data,
            headers=headers,
        )
        failure_msg = f"Failed to remove user {user.email} -- {user.splitwise_id}"
        assert response.status_code == 200, f"{failure_msg}: {response}"
        errors = response.json().get("errors")
        assert not errors, f"{failure_msg}: {response.json()}"

    flash("Synced Splitwise Group for event", "success")
    return redirect(event_url)
