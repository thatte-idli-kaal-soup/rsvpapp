import os

MONGODB_SETTINGS = {
    'host': os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/rsvpdata')
}
SECRET_KEY = os.environ.get('SECRET_KEY', 'Our awesome secret key')
# Other shit
TEXT1 = os.environ.get('TEXT1', "CloudYuga")
LOGO = os.environ.get(
    'LOGO',
    "https://raw.githubusercontent.com/cloudyuga/rsvpapp/master/static/cloudyuga.png",
)
COMPANY = os.environ.get('COMPANY', "CloudYuga Technology Pvt. Ltd.")
DEBUG = 'DEBUG' in os.environ
