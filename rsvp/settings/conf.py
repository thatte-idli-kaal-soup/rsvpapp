import os

MONGODB_SETTINGS = {
    "host": os.environ.get("MONGODB_URI", "mongodb://localhost:27017/rsvpdata")
}
SECRET_KEY = os.environ.get("SECRET_KEY", "Our awesome secret key")
# Flag to specify if users need to be approved to use the app
PRIVATE_APP = os.environ.get("PRIVATE_APP", "1") == "1"
# Other shit
TEXT1 = os.environ.get("TEXT1", "RSVPDemo")
LOGO = os.environ.get(
    "LOGO", "https://static.thenounproject.com/png/490034-200.png"
)
COMPANY = os.environ.get("COMPANY", "CloudYuga Technology Pvt. Ltd.")
DEBUG = "DEBUG" in os.environ
SOCIAL = [
    {
        "name": "Instagram",
        "icon": "instagram",
        "url": os.environ.get("SOCIAL_INSTAGRAM_URL", ""),
        "type": "account",
    },
    {
        "name": "YouTube",
        "icon": "youtube",
        "url": os.environ.get("SOCIAL_YOUTUBE_URL", ""),
        "type": "account",
    },
    {
        "name": "Heroku",
        "icon": "server",
        "url": "https://dashboard.heroku.com",
        "type": "account",
    },
    {
        "name": "Facebook",
        "icon": "facebook",
        "url": os.environ.get("SOCIAL_FACEBOOK_URL", ""),
        "type": "page",
    },
    {
        "name": "Google Drive",
        "icon": "google-drive",
        "description": "Use this drive to share media with the Marketing & Media team",
        "url": "https://drive.google.com/drive/folders/{}".format(
            os.environ.get("GOOGLE_DRIVE_MEDIA_DRIVE_ID", "")
        ),
        "type": "page",
    },
]
# Calendar settings
EVENT_DURATION = 7200  # 2 hours
TIMEZONE = "Asia/Kolkata"
