import os

MONGODB_SETTINGS = {
    'host': os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/rsvpdata')
}
SECRET_KEY = os.environ.get('SECRET_KEY', 'Our awesome secret key')
PRIVATE_APP = False
# Other shit
TEXT1 = os.environ.get('TEXT1', "CloudYuga")
LOGO = os.environ.get(
    'LOGO',
    "https://raw.githubusercontent.com/cloudyuga/rsvpapp/master/static/cloudyuga.png",
)
COMPANY = os.environ.get('COMPANY', "CloudYuga Technology Pvt. Ltd.")
DEBUG = 'DEBUG' in os.environ
SOCIAL = [
    {
        'name': 'Instagram',
        'url': 'https://www.instagram.com/thatteidlikaalsoup/',
        'type': 'account',
    },
    {
        'name': 'YouTube',
        'url': 'https://www.youtube.com/channel/UCq1eqfGIwd2Emnqy165FoTw',
        'type': 'account',
    },
    {
        'name': 'Facebook',
        'url': 'https://www.facebook.com/Thatteidlikaalsoup/',
        'type': 'page',
    },
    {
        'name': 'GitHub',
        'url': 'https://github.com/thatte-idli-kaal-soup/',
        'type': 'page',
    },
]
