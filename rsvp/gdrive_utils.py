# Standard library
import json
import os

# 3rd party
from apiclient.discovery import build
from google.oauth2 import service_account
import requests

# Local library
SERVICE_ACCOUNT_FILE = 'service_account_file.json'


def download_service_account_file():
    url = os.environ['GOOGLE_SERVICE_ACCOUNT_FILE_URL']
    with open(SERVICE_ACCOUNT_FILE, 'w') as f:
        json.dump(requests.get(url).json(), f)


def create_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        download_service_account_file()
    SCOPES = ['https://www.googleapis.com/auth/drive']
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build('drive', 'v3', credentials=credentials)
    return service


def update_permissions(service, file_id, emails):
    permissions = service.permissions().list(
        fileId=file_id, fields='permissions(id, emailAddress, role)'
    ).execute()
    permissions = [
        permission
        for permission in permissions.get('permissions', [])
        if 'emailAddress' in permission
    ]
    permission_emails = {
        permission['emailAddress'].lower() for permission in permissions
    }
    delete_permissions = [
        permission
        for permission in permissions
        if permission['emailAddress'].lower() not in emails
        and permission['role'] != 'owner'
        and 'gserviceaccount.com' not in permission['emailAddress']
    ]
    new_emails = [email for email in emails if email not in permission_emails]
    print('Adding {} permissions'.format(len(new_emails)))
    print('\n'.join(new_emails))
    for email in new_emails:
        body = {
            'type': 'user',
            'role': 'writer',
            'emailAddress': email,
            'sendNotificationEmail': False,
        }
        service.permissions().create(fileId=file_id, body=body).execute()
    print('Deleting {} permissions'.format(len(delete_permissions)))
    print(
        '\n'.join(
            permission['emailAddress'] for permission in delete_permissions
        )
    )
    for permission in delete_permissions:
        service.permissions().delete(
            fileId=file_id, permissionId=permission['id']
        ).execute()


def photos(service, root):
    q = "'{}' in parents and mimeType contains 'image/'"
    for sub_dir in walk_dir(service, root):
        photos = service.files().list(
            q=q.format(sub_dir['id']), fields='files(id)', pageSize=1000
        ).execute()[
            'files'
        ]
        yield from [
            {'gdrive_parent': sub_dir['id'], 'gdrive_id': photo['id']}
            for photo in photos
        ]


def walk_dir(service, root):
    q = "'{}' in parents and mimeType='{}'"
    mime_type = 'application/vnd.google-apps.folder'
    sub_dirs = service.files().list(
        q=q.format(root, mime_type), fields='files(id)'
    ).execute()[
        'files'
    ]
    yield from sub_dirs

    for sub_dir in sub_dirs:
        yield from walk_dir(service, sub_dir['id'])
