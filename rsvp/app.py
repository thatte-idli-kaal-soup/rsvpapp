import os

from flask import Flask, redirect, session, url_for
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer import oauth_authorized
from flask_login import LoginManager, login_user
from flaskext.versioned import Versioned

from .models import db, User, AnonymousUser
from .utils import format_date, rsvp_by

app = Flask(__name__)
app.config.from_envvar('SETTINGS')
versioned = Versioned(app)
db.init_app(app)
# Google OAuth stuff
blueprint = make_google_blueprint(
    client_id=os.environ['GOOGLE_CLIENT_ID'],
    client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    scope=["profile", "email"],
)
app.register_blueprint(blueprint, url_prefix="/login")
TEXT1 = app.config['TEXT1']
LOGO = app.config['LOGO']
COMPANY = app.config['COMPANY']


# Context processors
@app.context_processor
def inject_branding():
    return dict(TEXT1=TEXT1, LOGO=LOGO, COMPANY=COMPANY)


@oauth_authorized.connect_via(blueprint)
def google_logged_in(blueprint, token):
    response = google.get("/oauth2/v2/userinfo")
    info = response.json()
    email = info['email']
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        user = User(email=email, name=info['name'])
        user.save()
    # FIXME: May not be ideal, but we are trying not to annoy people!
    login_user(user, remember=True)
    return redirect(session.get('next_url', url_for('index')))


# Setup Login Manager
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.refresh_view = "refresh"
login_manager.session_protection = "basic"
login_manager.anonymous_user = AnonymousUser


@login_manager.user_loader
def load_user(user_id):
    try:
        return User.objects.get(email=user_id)

    except User.DoesNotExist:
        return


# Add template filters
app.jinja_env.filters['format_date'] = format_date
app.jinja_env.filters['rsvp_by'] = rsvp_by
