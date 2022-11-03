# Standard library
import datetime
import json
import os
from itertools import cycle

import requests

# 3rd party
from apiclient.discovery import build
from apiclient.http import MediaIoBaseUpload
from google.oauth2 import credentials as gcredentials
from google.oauth2 import service_account

# Local library
from .utils import event_absolute_url, random_string

SERVICE_ACCOUNT_FILE = "service_account_file.json"
SCOPES = {
    "drive": ["https://www.googleapis.com/auth/drive"],
    "calendar": ["https://www.googleapis.com/auth/calendar"],
}


def download_service_account_file():
    print("Downloading service account file to", SERVICE_ACCOUNT_FILE)
    url = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE_URL"]
    with open(SERVICE_ACCOUNT_FILE, "w") as f:
        json.dump(requests.get(url).json(), f)


def create_service(name="drive"):
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        download_service_account_file()
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES[name]
    )
    service = build(name, "v3", credentials=credentials)
    return service


def create_oauth_service(name="drive"):
    """Create an OAuth service as a user, instead of a service account.

    This means we can upload files as the user that we are logged in as,
    instead of using the service account. This means all the files uploaded
    count to this user's storage space, as opposed to being counted to the
    service account's storage.

    See https://stackoverflow.com/a/19766913 for steps to obtain refresh token

    """

    credentials = gcredentials.Credentials(
        token="random-token",
        refresh_token=os.environ["GDRIVE_REFRESH_TOKEN"],
        client_id=os.environ["GDRIVE_CLIENT_ID"],
        client_secret=os.environ["GDRIVE_CLIENT_SECRET"],
        scopes=SCOPES[name],
        token_uri="https://www.googleapis.com/oauth2/v4/token",
    )
    return build(name, "v3", credentials=credentials)


def create_folder(service, parent, name, description=""):
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "description": description,
    }
    if parent is not None:
        metadata["parents"] = [parent]
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder.get("id")


def create_root_folder(service, name="Media"):
    return create_folder(service, None, name)


def rename_folder(service, folder_id, name):
    metadata = {"name": name}
    folder = (
        service.files().update(fileId=folder_id, body=metadata, fields="id").execute()
    )
    return folder.get("id")


def move_file(service, file_id, src_id, dst_id):
    moved_file = (
        service.files()
        .update(
            fileId=file_id,
            removeParents=src_id,
            addParents=dst_id,
            fields="id",
        )
        .execute()
    )
    return moved_file.get("id")


def upload_photo(service, parent, name, mimetype, fd, description=""):
    metadata = {"name": name, "parents": [parent], "description": description}
    media = MediaIoBaseUpload(fd, mimetype=mimetype)
    photo = (
        service.files().create(body=metadata, media_body=media, fields="id").execute()
    )
    photo_id = photo.get("id")
    print("File ID: %s" % photo_id)
    return photo_id


def delete_content(service, gdrive_id):
    service.files().delete(fileId=gdrive_id).execute()


def update_permissions(service, file_id, emails):
    permissions = (
        service.permissions()
        .list(fileId=file_id, fields="permissions(id, emailAddress, role)")
        .execute()
    )
    permission_emails = {
        permission["emailAddress"].lower()
        for permission in permissions.get("permissions", [])
        if "emailAddress" in permission
    }
    delete_permissions = [
        permission
        for permission in permissions
        if permission["emailAddress"].lower() not in emails
        and permission["role"] != "owner"
        and "gserviceaccount.com" not in permission["emailAddress"]
    ]
    new_emails = [email for email in emails if email not in permission_emails]
    print("Adding {} permissions".format(len(new_emails)))
    print("\n".join(new_emails))
    for email in new_emails:
        body = {
            "type": "user",
            "role": "writer",
            "emailAddress": email,
            "sendNotificationEmail": False,
        }
        service.permissions().create(fileId=file_id, body=body).execute()
    print("Deleting {} permissions".format(len(delete_permissions)))
    print("\n".join(permission["emailAddress"] for permission in delete_permissions))
    for permission in delete_permissions:
        service.permissions().delete(
            fileId=file_id, permissionId=permission["id"]
        ).execute()


def photos(service, root):
    q = "'{}' in parents and mimeType contains 'image/'"
    for sub_dir in walk_dir(service, root):
        parent_id = sub_dir[-1]["id"] if isinstance(sub_dir, tuple) else sub_dir["id"]
        path = (
            " > ".join(s["name"] for s in sub_dir)
            if isinstance(sub_dir, tuple)
            else sub_dir["name"]
        )
        photos = (
            service.files()
            .list(
                q=q.format(parent_id),
                fields="files(id, imageMediaMetadata, thumbnailLink, createdTime)",
                pageSize=1000,
            )
            .execute()["files"]
        )
        yield from [
            {
                "gdrive_parent": parent_id,
                "gdrive_path": path,
                "gdrive_id": photo["id"],
                "gdrive_thumbnail": photo["thumbnailLink"],
                "gdrive_metadata": photo["imageMediaMetadata"],
                "gdrive_created_at": photo["createdTime"],
            }
            for photo in photos
        ]


def list_sub_dirs(service, root):
    q = "'{}' in parents and mimeType='{}'"
    mime_type = "application/vnd.google-apps.folder"
    sub_dirs = (
        service.files()
        .list(q=q.format(root, mime_type), fields="files(id, name)")
        .execute()["files"]
    )
    return sub_dirs


def list_files(service, folder_id):
    q = "'{}' in parents"
    files = (
        service.files()
        .list(q=q.format(folder_id), fields="files(id, name)")
        .execute()["files"]
    )
    return files


def flat_zip(x, y):
    if isinstance(y, tuple):
        return (x, *y)

    return (x, y)


def walk_dir(service, root):
    sub_dirs = list_sub_dirs(service, root)
    yield from sub_dirs

    for sub_dir in sub_dirs:
        yield from map(flat_zip, cycle([sub_dir]), walk_dir(service, sub_dir["id"]))


# Calendar

CALENDAR_TITLE = "RSVP App Events Calendar"


def get_calendar_id(service):
    page_token = None
    while True:
        calendar_list = service.calendarList().list(pageToken=page_token).execute()
        for calendar_list_entry in calendar_list["items"]:
            if calendar_list_entry["summary"] == CALENDAR_TITLE:
                return calendar_list_entry["id"]

        page_token = calendar_list.get("nextPageToken")
        if not page_token:
            break

    calendar = service.calendars().insert(body={"summary": CALENDAR_TITLE}).execute()
    return calendar["id"]


def get_calendar_acls(service, calendarId):
    page_token = None
    items = []
    while True:
        acls = service.acl().list(calendarId=calendarId, pageToken=page_token).execute()
        items.extend(acls["items"])
        page_token = acls.get("nextPageToken")
        if not page_token:
            break

    return items


def update_calendar_sharing(service, emails):
    calendarId = get_calendar_id(service)
    acls = get_calendar_acls(service, calendarId)
    readers = [
        acl
        for acl in acls
        if acl["role"] == "reader" and acl["scope"]["type"] == "user"
    ]
    permitted_users = {reader["scope"]["value"] for reader in readers}

    for reader in readers:
        email = reader["scope"]["value"]
        if email not in emails:
            ruleId = reader["id"]
            service.acl().delete(calendarId=calendarId, ruleId=ruleId).execute()
            print("Revoked access for {}".format(email))

    new_users = set(emails) - permitted_users
    for user in new_users:
        body = {"scope": {"type": "user", "value": user}, "role": "reader"}
        service.acl().insert(
            calendarId=calendarId, body=body, sendNotifications=True
        ).execute()
        print("Granted access to {}".format(user))


def generate_calendar_event_id(obj, type_):
    if type_ == "rsvp":
        key = obj.id
    elif type_ == "birthday":
        key = obj.email
    else:
        raise ValueError("Unknown Calendar Event Type: {}".format(type_))

    suffix = random_string()
    return "{prefix}:{key}:{suffix}".format(prefix=type_, key=key, suffix=suffix)


def delete_calendar_event(service, calendarId, iCalUID):
    events = (
        service.events().list(calendarId=calendarId, iCalUID=iCalUID).execute()["items"]
    )
    if len(events) == 1:
        event = events[0]
        service.events().delete(calendarId=calendarId, eventId=event["id"]).execute()
    else:
        print("Event not found: {}".format(iCalUID))


def _event_needs_update(existing, new):
    for key, value in new.items():
        if key == "iCalUID":
            continue
        if key not in existing or existing[key] != value:
            return True
    return False


def list_events(service, calendarId):
    events = service.events().list(calendarId=calendarId, maxResults=2500).execute()
    event_items = events["items"]
    while "nextPageToken" in events:
        events = service.events().list(calendarId=calendarId, maxResults=2500).execute()
        event_items = events["items"] + event_items
    return event_items


def cal_event_to_model_id(event):
    return event["iCalUID"].split(":", 2)[1]


def add_birthday(service, calendarId, user):
    body = make_birthday_body(user)
    print(f"Adding {body['summary']}...")
    service.events().insert(calendarId=calendarId, body=body).execute()


def update_birthday(service, calendarId, user, event):
    body = make_birthday_body(user)
    title = body["summary"]
    if not _event_needs_update(event, body):
        print(f"No update for {title}")
    else:
        print(f"Updating {title}")
        service.events().update(
            calendarId=calendarId, eventId=event["id"], body=body
        ).execute()


def make_birthday_body(user):
    title = "{}'s Birthday".format(user.nick_name)
    start_date = user.dob.strftime("%Y-%m-%d")
    end_date = (user.dob + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    iCalUID = generate_calendar_event_id(user, "birthday")
    body = {
        "start": {"date": start_date},
        "end": {"date": end_date},
        "recurrence": ["RRULE:FREQ=YEARLY"],
        "summary": title,
        "iCalUID": iCalUID,
    }
    return body


def delete_event(service, calendarId, event):
    print(f"Deleting {event['summary']}...")
    delete_calendar_event(service, calendarId, event["iCalUID"])


def make_rsvp_body(rsvp, timezone):
    title = rsvp.name
    start_date = rsvp.date
    end_date = rsvp.end_date
    iCalUID = generate_calendar_event_id(rsvp, "rsvp")
    url = event_absolute_url(rsvp)
    description = f"RSVP here: {url}\n\n {rsvp.description}"
    body = {
        "start": {"dateTime": start_date.isoformat(), "timeZone": timezone},
        "end": {"dateTime": end_date.isoformat(), "timeZone": timezone},
        "summary": title,
        "description": description,
        "iCalUID": iCalUID,
        "source": {
            "url": url,
            "title": "Go to RSVP app page",
        },
    }
    return body


def add_rsvp(service, calendarId, rsvp, timezone):
    body = make_rsvp_body(rsvp, timezone)
    print(f"Adding {body['summary']}...")
    service.events().insert(calendarId=calendarId, body=body).execute()


def update_rsvp(service, calendarId, rsvp, event, timezone):
    body = make_rsvp_body(rsvp, timezone)
    title = body["summary"]
    if not _event_needs_update(event, body):
        print(f"No update for {title}")
    else:
        print(f"Updating {title}")
        service.events().update(
            calendarId=calendarId, eventId=event["id"], body=body
        ).execute()
