import copy
import os
from urllib.parse import urlparse, urlunparse

from flask import (
    current_app,
    flash,
    render_template,
    redirect,
    url_for,
    request,
    send_file,
    session,
    make_response,
)
from flask_login import (
    current_user,
    fresh_login_required,
    login_required,
    logout_user,
)
from mongoengine.errors import DoesNotExist

from .gdrive_utils import create_service, list_sub_dirs
from .models import Event, GDrivePhoto, Post, RSVP, User, ANONYMOUS_EMAIL
from .utils import (
    format_date,
    generate_password,
    get_attendance,
    role_required,
    send_approved_email,
)
from . import app


@app.before_request
def redirect_heroku():
    """Redirect herokuapp requests to rsvp.thatteidlikaalsoup.team."""
    urlparts = urlparse(request.url)
    if urlparts.netloc == "thatte-idli-rsvp.herokuapp.com":
        urlparts_list = list(urlparts)
        urlparts_list[1] = "rsvp.thatteidlikaalsoup.team"
        return redirect(urlunparse(urlparts_list), code=301)


@app.route("/version-<version>/<path:static_file>")
def versioned_static(version, static_file):
    return send_file(static_file)


# Views ####
@app.route("/")
@login_required
def index():
    upcoming_events = Event.objects.filter(archived=False).order_by("date")
    return render_template("index.html", upcoming_events=upcoming_events)


@app.route("/archived")
@login_required
def archived():
    archived_events = Event.objects.filter(archived=True).order_by("-date")
    return render_template("archived.html", archived_events=archived_events)


@app.route("/event/<id>", methods=["GET"])
@login_required
def event(id):
    event = Event.objects(id=id).first()
    event_text = "{} - {}".format(event["name"], format_date(event["date"]))
    description = "RSVP for {}".format(event_text)
    approved_users = User.approved_users()
    return render_template(
        "event.html",
        count=event.rsvp_count,
        event=event,
        items=event.rsvps,
        active_rsvps=event.active_rsvps,
        approved_users=approved_users,
        TEXT2=event_text,
        description=description,
    )


@app.route("/new/<event_id>", methods=["POST"])
@login_required
def new_rsvp(event_id):
    event = Event.objects(id=event_id).first()
    email = request.form["email"].strip()
    note = request.form["note"].strip()
    try:
        print("Trying to fetch user with email {}".format(repr(email)))
        user = User.objects.get(email=email)
    except DoesNotExist:
        flash(
            "Could not find user with email, using anonymous user!", "warning"
        )
        user = User.objects.get(email=ANONYMOUS_EMAIL)
        note = "{}: {}".format(email, note) if note else email
    if not current_user.is_admin and event.archived:
        flash("Cannot modify an archived event!", "warning")
    elif len(event.active_rsvps.filter(user=user)) > 0:
        flash("{} has already RSVP-ed!".format(email), "warning")
    elif len(event.rsvps.filter(user=user)) > 0:
        rsvp = event.rsvps.get(user=user)
        rsvp.cancelled = False
        rsvp.note = note
        rsvp.save()
    elif email:
        rsvp_by = current_user.email if current_user.is_authenticated else None
        rsvp = RSVP(user=user, rsvp_by=rsvp_by, note=note)
        event.rsvps.append(rsvp)
        event.save()
    return redirect(url_for("event", id=event_id))


@app.route("/event", methods=["POST"])
def create_event():
    date = request.form["date"]
    time = request.form["time"]
    item_doc = {
        "name": request.form["event-name"],
        "date": "{} {}".format(date, time),
        "created_by": current_user.email
        if current_user.is_authenticated
        else None,
        "description": request.form.get("event-description", ""),
    }
    event = Event(**item_doc)
    event.save()
    return redirect(url_for("index"))


@app.route("/users", methods=["GET"])
@fresh_login_required
def users():
    role = request.values.get("role")
    gender = request.values.get("gender")
    users = User.approved_users()
    if role:
        users = users.filter(roles__in=[role])
    if gender:
        users = users.filter(gender=None if gender == "unknown" else gender)
    roles = sorted(
        {
            role
            for user in User.objects.all()
            for role in user.roles
            if not role.startswith(".")
        }
    )
    genders = set(filter(None, User.objects.values_list("gender"))).union(
        {"unknown"}
    )
    users = sorted(users, key=lambda u: u.name.lower())
    return render_template(
        "users.html",
        users=users,
        gender=gender,
        genders=genders,
        roles=roles,
        role=role,
    )


@app.route("/profile", methods=["GET", "POST"])
@fresh_login_required
def user_profile():
    if request.method == "GET":
        return render_template("user_form.html")

    email = request.form["email"]
    if email != current_user.email:
        flash("You can only modify your information", "danger")
    else:
        user = User.objects.get_or_404(email=email)
        user.upi_id = request.form["upi-id"].strip()
        user.blood_group = request.form["blood-group"].strip()
        user.nick = request.form["nick"].strip()
        user.dob = request.form["dob"] or None
        user.save()
        flash("Successfully updated your information", "info")
    return redirect(url_for("user_profile"))


@app.route("/approve_user/<email>", methods=["GET"])
@role_required("admin")
def approve_user(email):
    user = User.objects.get_or_404(email=email)
    if not user.has_role(".approved-user"):
        user.update(push__roles=".approved-user")
        send_approved_email(user)
    return redirect(url_for("users"))


@app.route("/disapprove_user/<email>", methods=["GET"])
@role_required("admin")
def disapprove_user(email):
    user = User.objects.get_or_404(email=email)
    user.delete()
    return redirect(url_for("users"))


@app.route("/approve_users/", methods=["GET"])
@role_required("admin")
def approve_users():
    users = sorted(
        User.objects(roles__nin=[".approved-user"]),
        key=lambda u: u.name.lower(),
    )
    return render_template("approve_users.html", users=users)


@app.route("/media", methods=["GET"])
@fresh_login_required
def media():
    social = copy.deepcopy(app.config["SOCIAL"])
    if current_user.has_any_role("admin", "social-admin"):
        for platform in social:
            if not platform["type"] == "account":
                continue

            platform["password"] = generate_password(
                platform["name"], app.secret_key
            )
    service = create_service()
    gdrive_root = os.environ["GOOGLE_DRIVE_MEDIA_DRIVE_ID"]
    gdrive_dirs = sorted(
        list_sub_dirs(service, gdrive_root), key=lambda x: x["name"]
    )
    photos = GDrivePhoto.new_photos()
    return render_template(
        "social.html", social=social, gdrive_dirs=gdrive_dirs, photos=photos
    )


@app.route("/features", methods=["GET"])
def features():
    return render_template("features.html")


# Login/Logout ####
@app.route("/login")
def login():
    next_url = request.args.get("next", url_for("index"))
    if current_user.is_authenticated:
        return redirect(next_url)

    session["next_url"] = next_url
    return render_template("login.html")


@app.route("/refresh")
def refresh():
    next_url = request.args.get("next", url_for("index"))
    session["next_url"] = next_url
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/approval_awaited/<name>")
def approval_awaited(name):
    return render_template("approval_awaited.html", name=name)


@app.route("/attendance", methods=["GET", "POST"])
@role_required("admin")
def attendance():
    if request.method == "GET":
        return render_template("attendance.html")

    start = request.form.get("start-date")
    end = request.form.get("end-date")
    events = Event.objects.filter(date__gte=start, date__lte=end)
    response = make_response(get_attendance(events))
    response.headers[
        "Content-Disposition"
    ] = "attachment; filename=attendance-{}--{}.csv".format(start, end)
    response.headers["Content-type"] = "text/csv"
    return response


@app.route("/posts")
@login_required
def show_posts():
    posts = Post.objects.order_by("-created_at")
    return render_template("posts.html", posts=posts)


@app.route("/post/<id>")
def show_post(id):
    post = Post.objects.get(id=id)
    if not post.public and not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    description = post.content[:100] if post.public else "Private post"
    return render_template("post.html", post=post, description=description)


@app.route("/edit-post/<id>", methods=["GET"])
@login_required
def edit_post(id):
    post = Post.objects.get(id=id)
    return render_template("post-editor.html", post=post)


@app.route("/post", methods=["GET", "POST"])
@login_required
def add_post():
    if request.method == "GET":
        return render_template("post-editor.html", post=None)
    post_id = request.form.get("post-id")
    data = {
        "title": request.form["title"],
        "content": request.form["content"],
        "public": request.form.get("public") is not None,
        "author": current_user.email,
    }
    if post_id:
        post = Post.objects.get(id=post_id)
        for key, value in data.items():
            setattr(post, key, value)
    else:
        post = Post(**data)
    post.save()
    return redirect(url_for("show_post", id=post.id))


# Miscellaneous views


@app.route("/onesta/<letters>")
@login_required
def onesta(letters):
    letters = letters.lower()
    users = [user for user in User.objects if letters in user.name.lower()]
    return render_template("names.html", users=users)


@app.route("/secret-santa/<event_id>", methods=["GET", "POST"])
@login_required
def secret_santa(event_id):
    from rsvp.rudolph import get_people, main

    people = get_people(event_id)
    if request.method == "GET":
        return render_template(
            "secret-santa.html", people=people, event_id=event_id
        )

    test_run = not request.form.get("live-run") == "on"
    pairs = main(people=people, test=test_run)
    pairs = [
        (User.objects.get(email=santa), User.objects.get(email=kiddo))
        for (santa, kiddo) in pairs
    ]
    if test_run:
        return render_template(
            "secret-santa.html",
            event_id=event_id,
            pairs=pairs,
            people=people,
            test_run=test_run,
        )
    else:
        return "Santas notified"
