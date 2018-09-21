# Standard library
import base64
import csv
from functools import wraps
import io
import os
from random import choice
import string

# 3rd party
from bson.objectid import ObjectId
from flask_login import current_user
from flask import current_app, render_template
import mistune
import requests
import sendgrid
from sendgrid.helpers.mail import Email, Content, Mail, Personalization
from werkzeug.security import pbkdf2_hex

ALLOWED_RATIOS = ((4, 3), (21, 9), (16, 9), (1, 1))


def gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def get_aspect_ratio(width, height, rotation):
    n = gcd(width, height)
    aspect_ratio = int(width / n), int(height / n)
    if aspect_ratio not in ALLOWED_RATIOS:
        aspect_ratio = ALLOWED_RATIOS[0]
    return "{}by{}".format(*aspect_ratio)


def get_attendance(events):
    users = {rsvp.user for e in events for rsvp in e.rsvps}
    dates = ["{:%Y-%m-%d}\n{}".format(e.date, e.name) for e in events]
    header = ["Names"] + dates
    attendance = {
        user: [e.active_rsvps.filter(user=user).count() for e in events]
        for user in users
    }
    rows = [
        [user.fetch().nick or user.fetch().name] + marked_attendance
        for user, marked_attendance in attendance.items()
    ]
    rows = sorted(rows, key=lambda x: x[0].lower())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue()


def format_date(value):
    try:
        format = (
            "%a, %d %b '%y, %H:%M"
            if value.hour != 0 or value.minute != 0
            else "%a, %d %b '%y"
        )
        return value.strftime(format)

    except ValueError:
        return value


def markdown_to_html(md):
    """Convert markdown to html."""
    if not md:
        md = ""
    return mistune.markdown(md, escape=False, hard_wrap=True, use_xhtml=True)


def random_id():
    return ObjectId(
        bytes(
            "".join(choice(string.ascii_letters) for _ in range(12)), "ascii"
        )
    )


def rsvp_by(rsvp):
    return rsvp.rsvp_by.fetch().name if rsvp.rsvp_by else "Anonymous"


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
    return base64.b85encode(bytes(tag_hash, "ascii"))[:n].decode("ascii")


def send_approval_email(user, admins):
    sg = sendgrid.SendGridAPIClient(apikey=os.environ.get("SENDGRID_API_KEY"))
    from_email = Email("noreply@thatteidlikaalsoup.team")
    to_emails = [
        Email("{} <{}>".format(admin.name, admin.email)) for admin in admins
    ]
    subject = "{} is awaiting your approval".format(user.name)
    content = Content(
        "text/plain", render_template("awaiting_approval.txt", user=user)
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
    sg = sendgrid.SendGridAPIClient(apikey=os.environ.get("SENDGRID_API_KEY"))
    from_email = Email("noreply@thatteidlikaalsoup.team")
    to_emails = [Email("{} <{}>".format(user.name, user.email))]
    subject = "Request approved".format(user.name)
    content = Content(
        "text/plain", render_template("request_approved.txt", user=user)
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


def send_message_zulip(to, subject, content, type_="private"):
    """Send a message to Zulip."""
    data = {"type": type_, "to": to, "subject": subject, "content": content}
    try:
        print(u'Sending message "%s" to %s (%s)' % (content, to, type_))
        zulip_api_url = os.environ["ZULIP_API_URL"]
        zulip_email = os.environ["ZULIP_EMAIL"]
        zulip_key = os.environ["ZULIP_KEY"]
        response = requests.post(
            zulip_api_url, data=data, auth=(zulip_email, zulip_key)
        )
        print(
            u"Post returned with %s: %s"
            % (response.status_code, response.content)
        )
        return response.status_code == 200

    except Exception as e:
        print(e)
        return False


def zulip_announce(sender, document, **kwargs):
    created = kwargs.get("created", False)
    announce = created or "description" in document._changed_fields
    if not announce:
        return

    if (
        "RSVP_HOST" not in os.environ
        or "ZULIP_ANNOUNCE_STREAM" not in os.environ
    ):
        print("Please set RSVP_HOST and ZULIP_ANNOUNCE_STREAM")
        return

    if created:
        # Fetch object from DB to be able to use validated/cleaned values
        document = sender.objects.get(id=document.id)
    url = "{}/event/{}".format(os.environ["RSVP_HOST"], str(document.id))
    title = "{:%Y-%m-%d %H:%M} - {}".format(document.date, document.name)
    content = render_template("zulip_announce.md", event=document, url=url)
    send_message_zulip(
        os.environ["ZULIP_ANNOUNCE_STREAM"], title, content, "stream"
    )


def zulip_announce_new_photos(new_paths, new_photos):
    title = "GDrive: New Photos uploaded"
    content = ""
    if new_paths:
        content += "{} new album(s) created\n\n".format(len(new_paths))
        urls = [
            "- [{}](https://drive.google.com/drive/folders/{}/)".format(p, id_)
            for (id_, p) in new_paths
        ]
        content += "\n".join(urls) + "\n\n"

    if new_photos:
        paths = {id_ for (id_, _) in new_paths}
        old_path_photos = [
            photo for photo in new_photos if photo.gdrive_parent not in paths
        ]
        if old_path_photos:
            n = len(old_path_photos)
            content += "{} new photos added to old albums".format(n)
            urls = [
                "- [{path}-{gid}](https://drive.google.com/file/d/{gid}/preview)".format(
                    path=photo.gdrive_path, gid=photo.gdrive_id
                )
                for photo in old_path_photos
            ]
            content += "\n".join(urls)

    send_message_zulip(
        os.environ["ZULIP_ANNOUNCE_STREAM"], title, content, "stream"
    )
