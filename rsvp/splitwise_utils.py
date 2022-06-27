import os

from flask import _app_ctx_stack as stack, flash
from flask_dance.consumer import OAuth2ConsumerBlueprint
from oauthlib.oauth2 import WebApplicationClient, BackendApplicationClient
import requests
from werkzeug.contrib.cache import SimpleCache


SPLITWISE_BASE_URL = "https://secure.splitwise.com/"
SPLITWISE_TOKEN = os.environ.get("SPLITWISE_TOKEN")
SPLITWISE_TOKEN_USER = os.environ.get("SPLITWISE_TOKEN_USER_ID")
AUTH_HEADERS = {"Authorization": f"Bearer {SPLITWISE_TOKEN}"}
CACHE = SimpleCache()


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


def calculate_dues(user_id):
    groups = get_groups()
    user_id = int(user_id)
    balances = [
        balance
        for group in groups
        for member in group["members"]
        for balance in member["balance"]
        if member["id"] == user_id
    ]
    currency = {balance["currency_code"] for balance in balances}
    assert len(currency) <= 1, f"Cannot support multiple currencies: {currency}"
    amounts = [float(balance["amount"]) for balance in balances]
    return -1 * sum(amounts)


def get_simplified_debts(user_id):
    groups = get_groups()
    user_id = int(user_id)
    debts = []
    for group in groups:
        members = {member["id"]: member for member in group["members"]}
        for debt in group["simplified_debts"]:
            if debt["from"] != user_id:
                continue
            member = members.get(debt["to"], {})
            member["name"] = f"{member.get('first_name')} {member.get('last_name')}"
            debt["to_member"] = member
            debt["to"] = str(debt["to"])
            debt["group_id"] = str(group["id"])
            debt["group_name"] = group["name"]
            debts.append(debt)

    return debts


def sync_rsvps_with_splitwise_group(group, users):
    # Add all currently active RSVP users to the Splitwise group
    members = {str(member["id"]) for member in group.get("members", [])}
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
    for member in members:
        # Don't remove SPLITWISE_TOKEN_USER, since we use that account to
        # manage groups. Also, don't remove active RSVP users
        if member == SPLITWISE_TOKEN_USER or member in user_splitwise_ids:
            continue
        data = {
            "group_id": group["id"],
            "user_id": member,
        }
        response = requests.post(
            f"{SPLITWISE_BASE_URL}/api/v3.0/remove_user_from_group",
            data=data,
            headers=AUTH_HEADERS,
        )
        success = response.json().get("success", False)
        if response.status_code != 200 or not success:
            failure_message = f"Could not remove {user.nick_name} from Splitwise group: {response.text}"
            flash(failure_message, "danger")
