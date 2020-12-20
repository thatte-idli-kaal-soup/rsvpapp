# Standard library
import base64
import csv
from datetime import datetime
from functools import wraps
import io
import os
from random import choice, shuffle
import re
import string

# 3rd party
import altair as alt
from bson.objectid import ObjectId
from flask_login import current_user
from flask import current_app, render_template
import mistune
import sendgrid
from sendgrid.helpers.mail import Email, Content, Mail, Personalization
from werkzeug.security import pbkdf2_hex
from dropbox import Dropbox


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


SLUG_RE = re.compile("[^A-Za-z]+")


class BootstrapMarkdownRenderer(mistune.Renderer):
    def block_quote(self, text):
        """Rendering <blockquote> with the given text and bootstrap class."""
        return (
            "<blockquote class='blockquote'>%s\n</blockquote>\n"
            % text.rstrip("\n")
        )

    def image(self, src, title, text):
        """Rendering a image with title and text, and bootstrap class."""
        html = super(BootstrapMarkdownRenderer, self).image(src, title, text)
        bs_class = "rounded mx-auto d-block"
        return html.replace("<img ", '<img class="{}"'.format(bs_class))

    def header(self, text, level, raw=None):
        """Rendering header/heading tags like ``<h1>`` ``<h2>``.

        Overridden to add an id to the headlines
        """
        id_ = get_slug(text)
        return '<h%d id="%s">%s</h%d>\n' % (level, id_, text, level)


def get_slug(text):
    return SLUG_RE.sub("-", text.casefold()).strip("-")


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


def format_gphoto_time(time):
    return datetime.strptime(time, "%Y:%m:%d %H:%M:%S").strftime("%d %b %Y")


renderer = BootstrapMarkdownRenderer()


def markdown_to_html(md):
    """Convert markdown to html."""
    if not md:
        md = ""
    return mistune.markdown(
        md, escape=False, hard_wrap=True, use_xhtml=True, renderer=renderer
    )


def random_id():
    return ObjectId(bytes(random_string(), "ascii"))


def random_string(n=12):
    return "".join(choice(string.ascii_letters) for _ in range(12))


def read_app_config():
    settings = os.environ["SETTINGS"]
    settings_path = os.path.join(
        os.path.abspath(os.path.dirname(__file__)), settings
    )
    config = {}
    with open(settings_path) as f:
        exec(f.read(), config)
    return config


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
    to_users = admins
    subject = "{} is awaiting your approval".format(user.name)
    body = render_template("awaiting_approval.txt", user=user)
    return send_email(to_users, subject, body)


def send_approved_email(user):
    to_users = [user]
    subject = "Request approved".format(user.name)
    body = render_template("request_approved.txt", user=user)
    return send_email(to_users, subject, body)


def send_email(to_users, subject, body):
    sg = sendgrid.SendGridAPIClient(apikey=os.environ.get("SENDGRID_API_KEY"))
    from_email = Email(os.environ.get("FROM_EMAIL", "noreply@thatteidlikaalsoup.team"))
    content = Content("text/plain", body)
    to_emails = [
        Email("{} <{}>".format(user.name, user.email)) for user in to_users
    ]
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


def event_absolute_url(event):
    return "{}/event/{}".format(os.environ["RSVP_HOST"], str(event.id))


def post_absolute_url(post):
    return "{}/post/{}".format(os.environ["RSVP_HOST"], str(post.id))


def get_random_photos(photos, n=20):
    shuffle(photos)
    return photos[:n]


def get_attendance_chart(source):
    color_scale = alt.Scale(
        domain=("attendance", "sessions"), range=["darkorange", "black"]
    )
    select_weekday = alt.selection_multi(
        name="weekday", fields=["weekday", "year"]
    )
    color = alt.condition(
        select_weekday, alt.value("orange"), alt.value("lightgray")
    )
    base = alt.Chart(source).encode(x="weekday:N", y="year:O", color=color)
    legend = (
        base.mark_rect()
        .add_selection(select_weekday)
        .properties(width=320, height=50)
    )
    text = (
        base.mark_text(baseline="middle", fontSize=8, fontWeight=200)
        .transform_joinaggregate(
            count="sum(attended)", groupby=["year", "weekday"]
        )
        .transform_joinaggregate(total="count()", groupby=["year", "weekday"])
        .encode(text="label:O", color=alt.value("black"))
        .transform_calculate(label='datum.count + " of " + datum.total')
    )
    chart = (
        alt.Chart(source)
        .mark_bar()
        .transform_filter(select_weekday)
        .transform_joinaggregate(sessions="count()", groupby=["month", "year"])
        .transform_joinaggregate(
            attendance="sum(attended)", groupby=["month", "year"]
        )
        .transform_fold(["sessions", "attendance"])
        .encode(
            y=alt.Y(
                "value:Q",
                title="attendance",
                stack=None,
                scale=alt.Scale(domain=(0, 30)),
            ),
            x=alt.X("month:O"),
            color=alt.Color("key:N", scale=color_scale),
        )
    )
    chart = chart & (legend + text)
    return chart.to_json()


def upload_file(path):
    dbx = Dropbox(os.environ["DROPBOX_ACCESS_TOKEN"])
    print("Uploading file {} to Dropbox".format(path))
    with open(path, "rb") as f:
        dbx.files_upload(f.read(), "/{}".format(os.path.basename(path)))
