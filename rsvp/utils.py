# Standard library
import os
import base64
from functools import wraps
from random import choice
import string

# 3rd party
from bson.objectid import ObjectId
from flask_login import current_user
from flask import current_app, render_template
import mistune
import sendgrid
from sendgrid.helpers.mail import Email, Content, Mail, Personalization
from werkzeug.security import pbkdf2_hex


def format_date(value):
    try:
        format = "%a, %d %b '%y, %H:%M" if value.hour != 0 or value.minute != 0 else "%a, %d %b '%y"
        return value.strftime(format)

    except ValueError:
        return value


def markdown_to_html(md):
    """Convert markdown to html."""
    if not md:
        md = ''
    return mistune.markdown(md, escape=False, hard_wrap=True, use_xhtml=True)


def random_id():
    return ObjectId(
        bytes(
            ''.join(choice(string.ascii_letters) for _ in range(12)), 'ascii'
        )
    )


def rsvp_by(rsvp):
    return rsvp.rsvp_by.fetch().name if rsvp.rsvp_by else 'Anonymous'


def rsvp_name(rsvp):
    if rsvp.user:
        user = rsvp.user.fetch()
        return user.nick or user.name

    else:
        return rsvp.name


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


def send_approval_email(user, admins):
    sg = sendgrid.SendGridAPIClient(apikey=os.environ.get('SENDGRID_API_KEY'))
    from_email = Email("noreply@thatteidlikaalsoup.team")
    to_emails = [
        Email("{} <{}>".format(admin.name, admin.email)) for admin in admins
    ]
    subject = "{} is awaiting your approval".format(user.name)
    content = Content(
        "text/plain", render_template('awaiting_approval.txt', user=user)
    )
    mail = Mail(from_email, subject, to_emails[0], content)
    for to_email in to_emails[1:]:
        personalization = Personalization()
        personalization.add_to(to_email)
        mail.add_personalization(personalization)
    try:
        response = sg.client.mail.send.post(request_body=mail.get())
    except Exception:
        # FIXME: Silently failing...
        return False

    return int(response.status_code / 200) == 2


def send_approved_email(user):
    sg = sendgrid.SendGridAPIClient(apikey=os.environ.get('SENDGRID_API_KEY'))
    from_email = Email("noreply@thatteidlikaalsoup.team")
    to_emails = [Email("{} <{}>".format(user.name, user.email))]
    subject = "Request approved".format(user.name)
    content = Content(
        "text/plain", render_template('request_approved.txt', user=user)
    )
    mail = Mail(from_email, subject, to_emails[0], content)
    for to_email in to_emails[1:]:
        personalization = Personalization()
        personalization.add_to(to_email)
        mail.add_personalization(personalization)
    try:
        response = sg.client.mail.send.post(request_body=mail.get())
    except Exception as e:
        # FIXME: Silently failing...
        print(e)
        return False

    return int(response.status_code / 200) == 2
