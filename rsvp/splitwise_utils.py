import os

from flask import _app_ctx_stack as stack
from flask_dance.consumer import OAuth2ConsumerBlueprint
from oauthlib.oauth2 import WebApplicationClient, BackendApplicationClient
import requests
from werkzeug.contrib.cache import SimpleCache


SPLITWISE_BASE_URL = "https://secure.splitwise.com/"
SPLITWISE_TOKEN = os.environ.get("SPLITWISE_TOKEN")
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


def get_groups():
    cache_key = "splitwise_groups"
    groups = CACHE.get(cache_key)
    if groups is None:
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
