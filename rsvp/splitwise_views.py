import os

from flask import redirect, url_for
from flask_dance.consumer import OAuth2ConsumerBlueprint
from flask_login import current_user, login_required

from .app import app

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
