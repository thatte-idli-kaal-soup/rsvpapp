import copy
import json
import mimetypes
import os
import re
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
    jsonify,
    send_from_directory,
)
from flask_login import (
    current_user,
    fresh_login_required,
    login_required,
    logout_user,
    login_user,
)
from mongoengine.errors import DoesNotExist, ValidationError

from .cloudinary_utils import image_url, list_images
from .gdrive_utils import (
    create_folder,
    create_oauth_service,
    list_sub_dirs,
    upload_photo,
)
from .models import (
    Bookmark,
    Event,
    GDrivePhoto,
    InterestedUser,
    Post,
    RSVP,
    User,
)
from .utils import (
    format_gphoto_time,
    generate_password,
    get_attendance,
    get_attendance_chart,
    get_random_photos,
    role_required,
    send_approved_email,
)
from .zulip_utils import zulip_event_responses
from . import app


@app.before_request
def redirect_heroku():
    """Redirect herokuapp requests to rsvp.thatteidlikaalsoup.team."""
    urlparts = urlparse(request.url)
    if urlparts.netloc == "thatte-idli-rsvp.herokuapp.com":
        urlparts_list = list(urlparts)
        urlparts_list[1] = "rsvp.thatteidlikaalsoup.team"
        return redirect(urlunparse(urlparts_list), code=301)


# Views ####


@app.route("/version-<version>/<path:static_file>")
def versioned_static(version, static_file):
    return send_file(static_file)


# Event Views #########################################################


@app.route("/")
@login_required
def index():
    upcoming_events = Event.objects.filter(archived=False).order_by("date")
    posts = Post.objects.filter(draft=False).order_by("-created_at")[:2]
    photos = list(GDrivePhoto.objects)
    photos = get_random_photos(photos) if photos else []
    return render_template(
        "index.html",
        upcoming_events=upcoming_events,
        posts=posts,
        photos=photos,
    )


@app.route("/calendar")
@login_required
def calendar():
    return render_template("calendar.html")


def add_rsvp(event, user, cancelled):
    rsvp = RSVP(rsvp_by=user.email, user=user.email, cancelled=cancelled)
    event.rsvps.append(rsvp)
    event.save()


@app.route("/event/<id>", methods=["GET"])
@login_required
def event(id):
    event = Event.objects(id=id).first()
    rsvp_param = request.args.get("attending")
    if rsvp_param is not None:
        filtered_rsvps = event.rsvps.filter(user=current_user)
        cancelled = not rsvp_param == "yes"
        if filtered_rsvps.count() == 0:
            add_rsvp(event, current_user, cancelled)
        else:
            rsvp = filtered_rsvps.first()
            rsvp.cancelled = cancelled
            rsvp.save()
        event.update_waitlist()

    description = "RSVP for {}".format(event.title)
    approved_users = User.approved_users()
    fields = ("name", "nick", "email")
    approved_users = [
        dict(zip(fields, user)) for user in approved_users.values_list(*fields)
    ]
    rsvps = event.all_rsvps
    count = event.rsvp_count
    female_count = len(event.female_rsvps)
    male_count = count - female_count
    return render_template(
        "event.html",
        count=count,
        male_count=male_count,
        female_count=female_count,
        event=event,
        items=rsvps,
        active_rsvps=event.active_rsvps,
        approved_users=approved_users,
        TEXT2=event.title,
        description=description,
        comments=zulip_event_responses(event),
    )


@app.route("/event/<id>/gdrive", methods=["GET", "POST"])
@login_required
def create_event_gdrive(id):
    event = Event.objects(id=id).first()
    if request.method == "GET":
        if event.gdrive_id:
            # FIXME: Redirect to the drive!
            return redirect(url_for("event", id=id))
        else:
            flash(
                "The event does not have a drive associated with it", "warning"
            )
            return redirect(url_for("event", id=id))
    gdrive_root = os.environ["GOOGLE_DRIVE_MEDIA_DRIVE_ID"]
    service = create_oauth_service()
    drive_name = "{} {}".format(event.date.strftime("%Y-%m"), event.name)
    description = "Drive for {} - {}".format(
        event.title, url_for("event", id=event.id, _external=True)
    )
    event.gdrive_id = create_folder(
        service, gdrive_root, drive_name, description
    )
    event.save()
    return redirect(url_for("event", id=id))


@app.route("/new_event", methods=["GET"])
@app.route("/edit_event/<id>", methods=["GET"])
@login_required
def event_editor(id=None):
    event = Event.objects(id=id).first() if id is not None else None

    # Verify that the user can edit the event
    if event and not event.can_edit(current_user):
        return redirect(url_for("index"))

    duration = app.config["EVENT_DURATION"]
    return render_template("event-editor.html", event=event, duration=duration)


@app.route("/event", methods=["POST"])
@login_required
def create_event():
    date = request.form["date"]
    time = request.form["time"]
    item_doc = {
        "name": request.form["event-name"],
        "rsvp_limit": int(request.form["event-rsvp-limit"]),
        "date": "{} {}".format(date, time),
        "created_by": (
            current_user.email if current_user.is_authenticated else None
        ),
        "description": request.form.get("event-description", ""),
    }
    end_date = request.form.get("end_date", "")
    end_time = request.form.get("end_time", "")
    if end_date and end_time:
        item_doc["_end_date"] = "{} {}".format(end_date, end_time)

    event_id = request.form.get("event_id")
    if event_id is None:
        event = Event(**item_doc)
    else:
        event = Event.objects.get(id=event_id)
        # Don't set created_by when editing!
        item_doc.pop("created_by", None)
        # NOTE: event.update can't be used since post/pre save hooks aren't called
        for key, value in item_doc.items():
            setattr(event, key, value)
    event.save()
    event.update_waitlist()
    return redirect(url_for("event", id=event.id))


@app.route("/search", methods=["POST"])
@login_required
def search():
    query = request.form.get("query")
    events = Event.objects.order_by("-date")
    if query:
        events = events.search_text(query).order_by("$text_score")

    return render_template("search.html", events=events, query=query)


# User Views ###########################################################


@app.route("/profile", methods=["GET", "POST"])
@fresh_login_required
def user_profile():
    if request.method == "GET":
        source = url_for("api_attendance")
        chart = get_attendance_chart(source)
        return render_template("profile.html", chart=chart)

    email = request.form["email"]
    if email != current_user.email:
        flash("You can only modify your information", "danger")
    else:
        user = User.objects.get_or_404(email=email)
        user.gender = request.form["gender"].strip()
        user.upi_id = request.form["upi-id"].strip()
        user.phone = request.form["phone"].strip()
        user.blood_group = request.form["blood-group"].strip()
        user.nick = request.form["nick"].strip()
        user.name = request.form["name"].strip()
        user.dob = request.form["dob"] or None
        user.hide_dob = request.form.get("hide_dob") is not None
        user.save()
        flash("Successfully updated your information", "info")
    return redirect(url_for("user_profile"))


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


# Login/Logout ####
@app.route("/dev_login")
def dev_login():
    next_url = request.args.get("next", url_for("index"))
    if not current_user.is_authenticated:
        session["next_url"] = next_url
        dev_email = "dev@example.com"
        try:
            user = User.objects.get(email=dev_email)
        except User.DoesNotExist:
            user = User(email=dev_email, name="Developer", gender="female")
            user.roles.append(".approved-user")
            user.save()
        login_user(user, remember=True)
    return redirect(next_url)


@app.route("/login")
def login():
    next_url = request.args.get("next", url_for("index"))
    if current_user.is_authenticated:
        return redirect(next_url)

    session["next_url"] = next_url
    try:
        title = next_url_title(next_url)
    except (DoesNotExist, ValidationError):
        title = None
    context = dict(TEXT1=title) if title else {}
    return render_template("login.html", **context)


def next_url_title(path):
    match = re.match("/(event|post)/(\w+)", path)
    if not match:
        return None
    if match.group(1) == "event":
        obj = Event.objects.get(id=match.group(2))
    elif match.group(1) == "post":
        obj = Post.objects.get(id=match.group(2))
    else:
        return None
    return obj.title


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


# Post Views ###########################################################


@app.route("/posts")
@login_required
def show_posts():
    posts = Post.objects.order_by("-created_at")
    return render_template(
        "posts.html", posts=posts, show_year=True, hide_all_link=True
    )


@app.route("/post/<id>")
def show_post(id):
    post = Post.objects.get(id=id)
    if not post.public and not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    description = post.content[:100] if post.public else "Private post"
    comments = zulip_event_responses(post)
    return render_template(
        "post.html", post=post, description=description, comments=comments
    )


@app.route("/edit-post/<id>", methods=["GET"])
@login_required
def edit_post(id):
    post = Post.objects.get(id=id)
    authors = User.approved_users().values_list("email", "name", "nick")
    return render_template("post-editor.html", post=post, authors=authors)


@app.route("/post", methods=["GET", "POST"])
@login_required
def add_post():
    if request.method == "GET":
        authors = User.approved_users().values_list("email", "name", "nick")
        return render_template("post-editor.html", post=None, authors=authors)
    post_id = request.form.get("post-id")
    authors = request.form.getlist("authors")
    if current_user.email not in authors:
        authors.append(current_user.email)
    authors = [User(pk=author) for author in authors]
    data = {
        "title": request.form["title"],
        "content": request.form["content"],
        "public": request.form.get("public") is not None,
        "draft": request.form.get("draft") is not None,
        "authors": authors,
    }
    if post_id:
        post = Post.objects.get(id=post_id)
        if not post.can_edit(current_user):
            return redirect(url_for("show_post", id=post.id))
        # NOTE: post.update can't be used since post/pre save hooks aren't called
        for key, value in data.items():
            setattr(post, key, value)
    else:
        post = Post(**data)
    post.save()
    return redirect(url_for("show_post", id=post.id))


# Image views ##########################################################


@app.route("/images/")
@login_required
def images():
    return render_template(
        "images.html", images=list_images(), image_url=image_url
    )


# Bookmark views #######################################################


@app.route("/bookmarks/")
@login_required
def show_bookmarks():
    return show_bookmarks_page(page=1)


@app.route("/bookmarks/<int:page>")
@login_required
def show_bookmarks_page(page=1):
    bookmarks = Bookmark.objects.order_by("-id")
    pagination = bookmarks.paginate(page=page, per_page=25)
    return render_template(
        "bookmarks.html", pagination=pagination, pages=pagination.iter_pages()
    )


# Miscellaneous views ##################################################


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
    service = create_oauth_service()
    gdrive_root = os.environ["GOOGLE_DRIVE_MEDIA_DRIVE_ID"]
    gdrive_dirs = sorted(
        list_sub_dirs(service, gdrive_root), key=lambda x: x["name"]
    )
    youtube_playlist = os.environ.get("YOUTUBE_PLAYLIST_ID")
    photos = GDrivePhoto.new_photos(7)
    return render_template(
        "media.html",
        social=social,
        gdrive_dirs=gdrive_dirs,
        photos=photos,
        youtube_playlist=youtube_playlist,
    )


@app.route("/photo-map", methods=["GET"])
@login_required
def photo_map():
    CAPTION_FMT = """
    Clicked on: {}</br>
    <a href="https://drive.google.com/file/d/{}/view" target="_blank">View Original</a>
    """
    data = [
        {
            "latitude": photo.gdrive_metadata["location"]["latitude"],
            "longitude": photo.gdrive_metadata["location"]["longitude"],
            "thumbnail": photo.gdrive_thumbnail,
            "caption": CAPTION_FMT.format(
                format_gphoto_time(photo.gdrive_metadata["time"])
                if "time" in photo.gdrive_metadata
                else "unknown",
                photo.gdrive_id,
            ),
        }
        for photo in GDrivePhoto.objects
        if "location" in photo.gdrive_metadata
    ]
    return render_template("photo-map.html", data=json.dumps(data))


@app.route("/features", methods=["GET"])
def features():
    return render_template("features.html")


@app.route("/request-demo", methods=["POST"])
def request_demo():
    email = request.form.get("email")
    try:
        InterestedUser.objects.create(email=email)
        return render_template("demo-request-success.html")
    except ValidationError:
        return redirect(url_for("features"))


@app.route("/demo-requests", methods=["GET"])
@role_required("admin")
def demo_requests():
    demo_requests = InterestedUser.objects.filter()
    return render_template("demo-requests.html", demo_requests=demo_requests)


@app.route("/onesta/<letters>")
@login_required
def onesta(letters):
    letters = letters.lower()
    users = [user for user in User.objects if letters in user.name.lower()]
    return render_template("names.html", users=users)


@app.route("/secret-santa/<event_id>", methods=["GET", "POST"])
@login_required
@role_required("secret-santa-admin")
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


@app.route("/manifest")
def manifest():
    data = {
        "short_name": "RSVP - {}".format(app.config["TEXT1"]),
        "name": "RSVP - {}".format(app.config["TEXT1"]),
        "icons": [
            {
                "src": "https://user-images.githubusercontent.com/315678/69935255-52b20780-14fa-11ea-9a50-5c3ff00cf288.png",
                "sizes": "192x192",
                "type": "image/png",
            },
            {
                "src": "https://user-images.githubusercontent.com/315678/69935256-52b20780-14fa-11ea-81e8-e042b608526a.png",
                "sizes": "512x512",
                "type": "image/png",
            },
        ],
        "start_url": "/",
        "background_color": "#ffffff",
        "display": "standalone",
        "scope": "/",
        "theme_color": "#ffffff",
        "serviceworker": {"src": "./static/sw.js", "scope": "/"},
        "share_target": {
            "action": "/share",
            "method": "POST",
            "enctype": "multipart/form-data",
            "params": {"files": [{"name": "photos", "accept": ["image/*"]}]},
        },
    }
    return jsonify(data)


@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js")


@app.route("/share/photos", methods=["GET"])
@login_required
def share_photos():
    service = create_oauth_service()
    gdrive_root = os.environ["GOOGLE_DRIVE_MEDIA_DRIVE_ID"]
    existing_dirs = sorted(
        list_sub_dirs(service, gdrive_root), key=lambda x: x["name"]
    )[::-1]
    return render_template("share-photos.html", existing_dirs=existing_dirs)


@app.route("/share/photos/create_dir", methods=["POST"])
@login_required
def create_photo_dir():
    service = create_oauth_service()
    gdrive_root = os.environ["GOOGLE_DRIVE_MEDIA_DRIVE_ID"]
    drive_name = request.json.get("title", "")
    drive_id = create_folder(service, gdrive_root, drive_name)
    return jsonify({"drive_id": drive_id}), 201


@app.route("/share", methods=["GET"])
@login_required
def share():
    return redirect(url_for("share_photos"))


@app.route("/share/photos/upload", methods=["GET", "POST"])
@login_required
def upload_photos():
    if request.method == "GET":
        return redirect(url_for("share_photos"))

    service = create_oauth_service()
    photos = request.files.getlist("photos")
    existing_id = request.form.get("existing_dir", "")
    drive_id = request.form.get("new_dir", "") or existing_id
    if not drive_id:
        return (
            jsonify({"error": "need an existing dir or a dir name specified"}),
            400,
        )

    name, email = current_user.name, current_user.email
    description = "Uploaded by {name} ({email})".format(name=name, email=email)
    for photo in photos:
        filename = photo.filename
        mimetype = (
            photo.content_type
            if photo.content_type is not None
            else mimetypes.guess_type(filename)[0]
        )
        upload_photo(
            service, drive_id, filename, mimetype, photo.stream, description
        )

    drive_url = "https://drive.google.com/drive/folders/{}".format(drive_id)
    return jsonify({"success": "true", "drive_url": drive_url})
