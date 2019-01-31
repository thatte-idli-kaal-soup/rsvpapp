import json
import os
from urllib.request import quote
from urllib.parse import urlparse

import arrow
from flask import render_template
from werkzeug.contrib.cache import SimpleCache
import zulip

from .utils import event_absolute_url, post_absolute_url

zulip_email = os.environ["ZULIP_EMAIL"]
zulip_key = os.environ["ZULIP_KEY"]
zulip_site = zulip_email.split("@")[-1]
zulip_stream = os.environ["ZULIP_ANNOUNCE_STREAM"]
zulip_client = zulip.Client(
    email=zulip_email, api_key=zulip_key, site=zulip_site
)
cache = SimpleCache()


def send_message_zulip(to, subject, content, type_="private"):
    """Send a message to Zulip."""
    data = {"type": type_, "to": to, "subject": subject, "content": content}
    try:
        print(u'Sending message "%s" to %s (%s)' % (content, to, type_))
        response = zulip_client.send_message(data)
        print(
            u"Post returned with %s: %s"
            % (response.status_code, response.content)
        )
        return response.status_code == 200

    except Exception as e:
        print(e)
        return False


def zulip_title(event, truncate=False):
    if hasattr(event, "date"):
        title = "{:%Y-%m-%d %H:%M} - {}".format(event.date, event.name).strip()
    else:
        title = event.title  # post
    if truncate and len(title) > 60:
        title = title[:57] + "..."
    return title


def zulip_announce_event(sender, document, **kwargs):
    created = kwargs.get("created", False)
    announce = created or "description" in document._changed_fields
    if not announce:
        return

    if "RSVP_HOST" not in os.environ:
        print("Please set RSVP_HOST")
        return

    if created:
        # Fetch object from DB to be able to use validated/cleaned values
        document = sender.objects.get(id=document.id)
    url = event_absolute_url(document)
    title = zulip_title(document)
    content = render_template("zulip_announce.md", event=document, url=url)
    send_message_zulip(zulip_stream, title, content, "stream")


def zulip_announce_post(sender, document, **kwargs):
    created = kwargs.get("created", False)
    if not created:
        return

    if "RSVP_HOST" not in os.environ:
        print("Please set RSVP_HOST")
        return

    if created:
        # Fetch object from DB to be able to use validated/cleaned values
        document = sender.objects.get(id=document.id)

    url = post_absolute_url(document)
    title = zulip_title(document.title)
    send_message_zulip(zulip_stream, title, document.content, "stream")


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

    send_message_zulip(zulip_stream, title, content, "stream")


def zulip_event_url(event):
    """Return the Zulip url given the title. """
    zulip_api_url = os.environ.get("ZULIP_API_URL")
    if not zulip_api_url:
        return ""

    # We just replicate how Zulip creates/manages urls.
    # https://github.com/zulip/zulip/blob/33295180a918fcd420428d9aa2fb737b864cacaf/zerver/lib/notifications.py#L34
    # Some browsers zealously URI-decode the contents of window.location.hash.
    # So Zulip hides the URI-encoding by replacing '%' with '.'
    def replace(x):
        return (
            quote(x.encode("utf-8"), safe="")
            .replace(".", "%2E")
            .replace("%", ".")
        )

    title = zulip_title(event, truncate=True)
    title = replace(title)
    stream = replace(zulip_stream)
    host = urlparse(zulip_api_url).netloc
    return "https://{}/#narrow/stream/{}/topic/{}".format(host, stream, title)


def zulip_event_responses(event):
    messages = cache.get(event.id)
    if messages is not None:
        return json.loads(messages)
    topic = zulip_title(event, truncate=True)
    data = {
        "apply_markdown": True,
        "num_before": 1000,
        "num_after": 0,
        "anchor": 1000000000000000,
        "narrow": [
            {"negated": False, "operator": "stream", "operand": zulip_stream},
            {"negated": False, "operator": "topic", "operand": topic},
        ],
    }
    response = zulip_client.get_messages(data)
    messages = response.get("messages", [])
    messages = [msg for msg in messages if "-bot@" not in msg["sender_email"]]
    messages = [
        msg
        for msg in messages
        if not (
            "mentioned" in msg["flags"]
            and msg["content"].startswith('<p><span class="user-mention"')
        )
    ]
    for message in messages:
        message["timestamp"] = arrow.get(message["timestamp"]).humanize()

    cache.set(event.id, json.dumps(messages), timeout=60)
    return messages
