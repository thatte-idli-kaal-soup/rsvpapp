# Standard library
from itertools import cycle
import json
import os

# 3rd party
from apiclient.discovery import build
from apiclient.http import HttpError
from google.oauth2 import service_account
import requests

# Local library
SERVICE_ACCOUNT_FILE = "service_account_file.json"
SCOPES = {
    "drive": ["https://www.googleapis.com/auth/drive"],
    "calendar": ["https://www.googleapis.com/auth/calendar"],
}


def download_service_account_file():
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


def update_permissions(service, file_id, emails):
    permissions = (
        service.permissions()
        .list(fileId=file_id, fields="permissions(id, emailAddress, role)")
        .execute()
    )
    permissions = [
        permission
        for permission in permissions.get("permissions", [])
        if "emailAddress" in permission
    ]
    permission_emails = {
        permission["emailAddress"].lower() for permission in permissions
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
    print(
        "\n".join(
            permission["emailAddress"] for permission in delete_permissions
        )
    )
    for permission in delete_permissions:
        service.permissions().delete(
            fileId=file_id, permissionId=permission["id"]
        ).execute()


def photos(service, root):
    q = "'{}' in parents and mimeType contains 'image/'"
    for sub_dir in walk_dir(service, root):
        parent_id = (
            sub_dir[-1]["id"] if isinstance(sub_dir, tuple) else sub_dir["id"]
        )
        path = (
            " > ".join(s["name"] for s in sub_dir)
            if isinstance(sub_dir, tuple)
            else sub_dir["name"]
        )
        photos = (
            service.files()
            .list(
                q=q.format(parent_id),
                fields="files(id, imageMediaMetadata, createdTime)",
                pageSize=1000,
            )
            .execute()["files"]
        )
        yield from [
            {
                "gdrive_parent": parent_id,
                "gdrive_path": path,
                "gdrive_id": photo["id"],
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


def flat_zip(x, y):
    if isinstance(y, tuple):
        return (x, *y)

    return (x, y)


def walk_dir(service, root):
    sub_dirs = list_sub_dirs(service, root)
    yield from sub_dirs

    for sub_dir in sub_dirs:
        yield from map(
            flat_zip, cycle([sub_dir]), walk_dir(service, sub_dir["id"])
        )


# Calendar

CALENDAR_TITLE = "RSVP App Events Calendar"


def get_calendar_id(service):
    page_token = None
    while True:
        calendar_list = (
            service.calendarList().list(pageToken=page_token).execute()
        )
        for calendar_list_entry in calendar_list["items"]:
            if calendar_list_entry["summary"] == CALENDAR_TITLE:
                return calendar_list_entry["id"]

        page_token = calendar_list.get("nextPageToken")
        if not page_token:
            break

    calendar = (
        service.calendars().insert(body={"summary": CALENDAR_TITLE}).execute()
    )
    return calendar["id"]


def get_calendar_acls(service, calendarId):
    page_token = None
    items = []
    while True:
        acls = service.acl().list(calendarId=calendarId).execute()
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
            service.acl().delete(
                calendarId=calendarId, ruleId=ruleId
            ).execute()
            print("Revoked access for {}".format(email))

    new_users = set(emails) - permitted_users
    for user in new_users:
        body = {"scope": {"type": "user", "value": user}, "role": "reader"}
        service.acl().insert(
            calendarId=calendarId, body=body, sendNotifications=True
        ).execute()
        print("Granted access to {}".format(user))


def add_birthday(service, user):
    calendarId = get_calendar_id(service)
    title = "{}'s Birthday".format(user.nick or user.name)
    date = user.dob.strftime("%Y-%m-%d")
    iCalUID = "birthday:{}".format(user.email)
    body = {
        "start": {"date": date},
        "end": {"date": date},
        "recurrence": ["RRULE:FREQ=YEARLY"],
        "summary": title,
        "iCalUID": iCalUID,
    }
    add_or_update_event(service, calendarId, iCalUID, body)


def add_or_update_event(service, calendarId, iCalUID, body):
    try:
        service.events().insert(calendarId=calendarId, body=body).execute()
        print("Added {}".format(iCalUID))
    except HttpError as e:
        event = (
            service.events()
            .list(calendarId=calendarId, iCalUID=iCalUID)
            .execute()["items"][0]
        )
        if _event_needs_update(event, body):
            service.events().update(
                calendarId=calendarId, eventId=event["id"], body=body
            ).execute()
            print("Updated {}".format(iCalUID))
        else:
            print("No updates to {}".format(iCalUID))


def _event_needs_update(existing, new):
    for key, value in new.items():
        if key not in existing or existing[key] != value:
            return True
    return False
