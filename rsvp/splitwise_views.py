from functools import partial
import os

from flask import redirect, url_for, _app_ctx_stack as stack, flash, request, session
from flask_dance.consumer import OAuth2ConsumerBlueprint, oauth_authorized
from flask_login import current_user, login_required
from flask.globals import LocalProxy, _lookup_app_object
from oauthlib.oauth2 import WebApplicationClient, BackendApplicationClient

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
    flash(f"Your Splitwise ID {current_user.splitwise_id} has been saved.")
    return redirect(next_url)


@app.route("/splitwise/sync_group/<event_id>", methods=["POST"])
def sync_splitwise_group(event_id):
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
        create_url = "/api/v3.0/create_group"
        group = splitwise.post(create_url, data=data).json()["group"]
        event.splitwise_group_id = str(group["id"])
        event.save()
        created = True
    else:
        created = False
        get_url = "/api/v3.0/get_group/{}".format(event.splitwise_group_id)
        group = splitwise.post(get_url).json()["group"]

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
        splitwise.post("/api/v3.0/add_user_to_group", data=data)

    # If a group already existed, remove users in the group who don't have an RSVP
    if not created:
        members = group["members"]
        for member in members:
            splitwise_id, email = str(member["id"]), member["email"]
            try:
                user = User.objects.get(splitwise_id=splitwise_id)
            except User.DoesNotExist:
                try:
                    user = User.objects.get(email=email)
                except User.DoesNotExist:
                    user = None

            if user is None:
                continue

            if event.active_rsvps.filter(user=user).count():
                continue

            data = {
                "group_id": event.splitwise_group_id,
                "user_id": splitwise_id,
            }
            splitwise.post("/api/v3.0/remove_user_from_group", data=data)

    return redirect(url_for("event", id=event.id))
