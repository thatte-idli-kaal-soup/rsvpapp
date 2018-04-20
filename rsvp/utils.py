# Standard library
import base64
from functools import wraps
from random import choice
import string

# 3rd party
from bson.objectid import ObjectId
from flask_login import current_user
from flask import current_app, render_template
from werkzeug.security import pbkdf2_hex


def format_date(value):
    try:
        format = "%a, %d %b '%y, %H:%M" if value.hour != 0 or value.minute != 0 else "%a, %d %b '%y"
        return value.strftime(format)

    except ValueError:
        return value


def random_id():
    return ObjectId(
        bytes(
            ''.join(choice(string.ascii_letters) for _ in range(12)), 'ascii'
        )
    )


def rsvp_by(rsvp):
    return rsvp.rsvp_by.fetch().name if rsvp.rsvp_by else 'Anonymous'


def role_required(role="ALL"):

    def wrapper(func):

        @wraps(func)
        def decorated_view(*args, **kwargs):
            if current_app.login_manager._login_disabled:
                return func(*args, **kwargs)

            elif not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()

            elif not current_user.has_role(role):
                return render_template("errors/403.html"), 403

            return func(*args, **kwargs)

        return decorated_view

    return wrapper


def generate_password(tag, salt, n=32):
    tag_hash = pbkdf2_hex("{}-password".format(tag), salt)
    return base64.b85encode(bytes(tag_hash, 'ascii'))[:n].decode('ascii')
