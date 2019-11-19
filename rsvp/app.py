import datetime
import os

from flask import Flask, redirect, session, url_for
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer import oauth_authorized
from flask_login import current_user, LoginManager, login_user
from flask_sslify import SSLify
from flaskext.versioned import Versioned

from .models import db, GDrivePhoto, Post, User, AnonymousUser, ANONYMOUS_EMAIL
from .utils import (
    format_date,
    format_gphoto_time,
    rsvp_by,
    rsvp_name,
    send_approval_email,
)
from .zulip_utils import zulip_event_url


app = Flask(__name__)
app.config.from_envvar("SETTINGS")
if "DYNO" in os.environ:
    # only trigger SSLify if the app is running on Heroku
    sslify = SSLify(app)
versioned = Versioned(app)
db.init_app(app)

# Create anonymous user
try:
    User.objects.get(email=ANONYMOUS_EMAIL)
except User.DoesNotExist:
    User.objects.create(email=ANONYMOUS_EMAIL, name="Unknown User")

# Google OAuth stuff
blueprint = make_google_blueprint(
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    scope=[
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "openid",
    ],
)
app.register_blueprint(blueprint, url_prefix="/login")
TEXT1 = app.config["TEXT1"]
LOGO = app.config["LOGO"]


# Context processors
@app.context_processor
def inject_branding():
    return dict(TEXT1=TEXT1, LOGO=LOGO)


@app.context_processor
def inject_demo_warning():
    return dict(private_app=app.config["PRIVATE_APP"])


@app.context_processor
def inject_notifications():
    extra_context = dict()

    # Unapproved users
    if current_user and current_user.is_admin:
        approval_awaited_count = User.objects(
            roles__nin=[".approved-user"]
        ).count()
        extra_context["approval_awaited_count"] = approval_awaited_count

    # New posts
    two_days = datetime.datetime.now() - datetime.timedelta(days=2)
    recent_post_count = Post.objects.filter(
        created_at__gte=two_days, draft=False
    ).count()
    extra_context["recent_post_count"] = recent_post_count

    # New photos
    recent_photo_count = GDrivePhoto.new_photos().count()
    extra_context["recent_photo_count"] = recent_photo_count

    return extra_context


@oauth_authorized.connect_via(blueprint)
def google_logged_in(blueprint, token):
    response = google.get("/oauth2/v2/userinfo")
    info = response.json()
    email = info["email"]
    try:
        user = User.objects.get(email=email)
        created = False
    except User.DoesNotExist:
        user = User(email=email, name=info["name"], gender=info.get("gender"))
        user.save()
        created = True
    if not app.config["PRIVATE_APP"] or user.has_role(".approved-user"):
        # FIXME: May not be ideal, but we are trying not to annoy people!
        login_user(user, remember=True)
        next_ = redirect(session.get("next_url", url_for("index")))
    else:
        if created:
            admins = User.objects(roles__in=["admin"])
            # FIXME: Should we let the user know if the mail sending failed?
            send_approval_email(user, admins)
        next_ = redirect(url_for("approval_awaited", name=user.name))
    return next_


# Setup Login Manager
login_manager = LoginManager(app)
login_manager.login_view = (
    "dev_login" if os.environ["NO_GOOGLE_AUTH"] == "1" else "login"
)
login_manager.refresh_view = "refresh"
login_manager.session_protection = "basic"
login_manager.anonymous_user = AnonymousUser


@login_manager.user_loader
def load_user(user_id):
    try:
        return User.objects.get(email=user_id)

    except User.DoesNotExist:
        return


@login_manager.request_loader
def load_token_user(request):
    token_header = request.headers.get("Authorization", "").strip()
    if not token_header:
        return

    token = token_header.split()[-1]
    if not (token and token == os.environ["ZULIP_RSVP_TOKEN"]):
        return

    try:
        user = User.objects.get(email=ANONYMOUS_EMAIL)
    except User.DoesNotExist:
        user = User.objects(email=ANONYMOUS_EMAIL, name="Bot User")
        user.save()
    return user


# Add template filters
app.jinja_env.filters["format_date"] = format_date
app.jinja_env.filters["format_gphoto_time"] = format_gphoto_time
app.jinja_env.filters["rsvp_by"] = rsvp_by
app.jinja_env.filters["rsvp_name"] = rsvp_name
app.jinja_env.filters["zulip_event_url"] = zulip_event_url
