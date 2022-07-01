import os

from flask import _app_ctx_stack as stack, flash, url_for, redirect
from flask_dance.consumer import OAuth2ConsumerBlueprint
import requests
from werkzeug.contrib.cache import SimpleCache


SPLITWISE_BASE_URL = "https://secure.splitwise.com/"
SPLITWISE_TOKEN = os.environ.get("SPLITWISE_TOKEN")
SPLITWISE_TOKEN_USER = int(os.environ.get("SPLITWISE_TOKEN_USER_ID", "0"))
SPLITWISE_DUES_LIMIT = int(os.environ.get("SPLITWISE_DUES_LIMIT", "100"))
AUTH_HEADERS = {"Authorization": f"Bearer {SPLITWISE_TOKEN}"}
CACHE = SimpleCache()


def make_splitwise_blueprint(client_id=None, client_secret=None):
    splitwise_bp = OAuth2ConsumerBlueprint(
        "splitwise",
        __name__,
        client_id=client_id,
        client_secret=client_secret,
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


def get_groups(force_refresh=False):
    cache_key = "splitwise_groups"
    groups = CACHE.get(cache_key)
    if groups is None or force_refresh:
        url = f"{SPLITWISE_BASE_URL}/api/v3.0/get_groups"
        response = requests.get(url, headers=AUTH_HEADERS)
        assert response.status_code == 200, "Could not fetch groups for user."
        # NOTE: If this API call is being paginated or something, we could use
        # the /api/v3.0/get_main_data end-point, which the web UI seems to use.
        groups = response.json().get("groups", [])
        # Ignore direct transactions group which has the ID 0
        groups = [group for group in groups if group["id"] != 0]
        CACHE.set(cache_key, groups)  # default_timeout = 5mins
    return groups


def get_friends(force_refresh=False):
    cache_key = "splitwise_friends"
    friends = CACHE.get(cache_key)
    if friends is None or force_refresh:
        url = f"{SPLITWISE_BASE_URL}/api/v3.0/get_friends"
        response = requests.get(url, headers=AUTH_HEADERS)
        assert response.status_code == 200, "Could not fetch friends for user."
        # NOTE: If this API call is being paginated or something, we could use
        # the /api/v3.0/get_main_data end-point, which the web UI seems to use.
        friends = response.json().get("friends", [])
        CACHE.set(cache_key, friends)  # default_timeout = 5mins
    return friends


def calculate_dues(user_id):
    groups = get_groups()
    debts = [
        debt
        for group in groups
        for debt in group["simplified_debts"]
        if debt["from"] == user_id
    ]
    currency = {debt["currency_code"] for debt in debts}
    assert len(currency) <= 1, f"Cannot support multiple currencies: {currency}"
    amounts = [float(debt["amount"]) for debt in debts]
    return sum(amounts)


def get_simplified_debts(user_id):
    groups = get_groups()
    debts = []
    for group in groups:
        members = {member["id"]: member for member in group["members"]}
        for debt in group["simplified_debts"]:
            if debt["from"] != user_id:
                continue
            member = members.get(debt["to"], {})
            member["name"] = f"{member.get('first_name')} {member.get('last_name')}"
            debt["to_member"] = member
            debt["to"] = debt["to"]
            debt["group_id"] = group["id"]
            debt["group_name"] = group["name"]
            debts.append(debt)

    return debts


def sync_rsvps_with_splitwise_group(group, users):
    # Add all currently active RSVP users to the Splitwise group
    members = {member["id"] for member in group.get("members", [])}
    for user in users:
        if user.splitwise_id in members:
            continue
        data = {
            "group_id": group["id"],
            "user_id": user.splitwise_id,
        }
        response = requests.post(
            f"{SPLITWISE_BASE_URL}/api/v3.0/add_user_to_group",
            data=data,
            headers=AUTH_HEADERS,
        )
        success = response.json().get("success", False)
        if response.status_code != 200 or not success:
            failure_message = (
                f"Could not add {user.nick_name} to Splitwise group: {response.text}"
            )
            flash(failure_message, "danger")

    # Remove all users who are don't have active RSVPs
    user_splitwise_ids = {user.splitwise_id for user in users}
    for member_id in members:
        # Don't remove SPLITWISE_TOKEN_USER, since we use that account to
        # manage groups. Also, don't remove active RSVP users
        if member_id == SPLITWISE_TOKEN_USER or member_id in user_splitwise_ids:
            continue
        data = {
            "group_id": group["id"],
            "user_id": member_id,
        }
        response = requests.post(
            f"{SPLITWISE_BASE_URL}/api/v3.0/remove_user_from_group",
            data=data,
            headers=AUTH_HEADERS,
        )
        success = response.json().get("success", False)
        if response.status_code != 200 or not success:
            member = [m for m in group.get("members", []) if m["id"] == member_id][0]
            member_name = f"{member['first_name']} {member['last_name']}"
            failure_message = (
                f"Could not remove {member_name} from Splitwise group: {response.text}"
            )
            flash(failure_message, "danger")


def get_or_create_splitwise_group(event, users):
    if not ensure_users_splitwise_ids(event, users):
        return

    group = None
    # Try to get the Splitwise Group
    if event.splitwise_group_id:
        # NOTE: Ideally, we'd like to update group title/description but
        # Splitwise API doesn't seem to have an end-point for that?!

        # NOTE: We don't use data from get_groups(force_refresh=True), since we
        # want to get an error message if the group was deleted.
        get_url = f"{SPLITWISE_BASE_URL}/api/v3.0/get_group/{event.splitwise_group_id}"
        data = requests.get(get_url, headers=AUTH_HEADERS).json()
        group = data.get("group")
        error = data.get("errors", {}).get("base", [""])[0]
        deleted_error = "Invalid API Request: record not found"
        if group is None and error != deleted_error:
            flash(f"Could not sync with Splitwise. Failure: {data}", "danger")
            return

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

    return group


def splitwise_create_group_hook(sender, document, **kwargs):
    if document.is_paid and (
        kwargs.get("created") or "is_paid" in document._changed_fields
    ):
        # Fetch object from DB to be able to use validated/cleaned values
        event = sender.objects.get(id=document.id)
        users = [rsvp.user.fetch() for rsvp in event.active_rsvps]
        get_or_create_splitwise_group(event, users)


def ensure_users_splitwise_ids(event, users):
    if not all(user.splitwise_connected for user in users):
        missing_nicks = [user.nick_name for user in users if not user.splitwise_id]
        flash(
            f"Cannot create Splitwise group since some users have not connected Splitwise: "
            f"{', '.join(missing_nicks)}",
            "danger",
        )
        return False


def ensure_splitwise_ids_hook(sender, document, **kwargs):
    if document.is_paid and (
        kwargs.get("created") or "is_paid" in document._changed_fields
    ):
        users = [rsvp.user.fetch() for rsvp in document.active_rsvps]
        if not ensure_users_splitwise_ids(document, users):
            document.is_paid = False
