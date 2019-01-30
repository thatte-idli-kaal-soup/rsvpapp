import os
from urllib.request import quote
from urllib.parse import urlparse

from flask import render_template
import zulip

from .utils import event_absolute_url

zulip_email = os.environ["ZULIP_EMAIL"]
zulip_key = os.environ["ZULIP_KEY"]
zulip_site = zulip_email.split("@")[-1]
zulip_client = zulip.Client(
    email=zulip_email, api_key=zulip_key, site=zulip_site
)


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


def zulip_title(event):
    return "{:%Y-%m-%d %H:%M} - {}".format(event.date, event.name)


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
    url = event_absolute_url(document)
    title = zulip_title(document)
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

    title = zulip_title(event).strip()
    if len(title) > 60:
        title = title[:57] + "..."
    title = replace(title)
    stream = replace(os.environ["ZULIP_ANNOUNCE_STREAM"])
    host = urlparse(zulip_api_url).netloc
    return "https://{}/#narrow/stream/{}/topic/{}".format(host, stream, title)
