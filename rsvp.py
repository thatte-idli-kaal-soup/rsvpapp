import datetime
import json
import os
from random import choice
import string
from urllib.parse import urlparse, urlunparse

from auth import Auth
from bson.objectid import ObjectId
from flask import Flask, render_template, redirect, url_for, request, session, send_file
from flask_login import LoginManager, login_required, login_user, logout_user, current_user
from flaskext.versioned import Versioned
from pymodm import connect, fields, MongoModel
from pymongo import MongoClient, ASCENDING, DESCENDING
from requests.exceptions import HTTPError
from requests_oauthlib import OAuth2Session

app = Flask(__name__)
versioned = Versioned(app)
app.config.update(DEBUG=True, SECRET_KEY='...')
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
TEXT1 = os.environ.get('TEXT1', "CloudYuga")
TEXT2 = os.environ.get('TEXT2', "Garage RSVP")
LOGO = os.environ.get(
    'LOGO',
    "https://raw.githubusercontent.com/cloudyuga/rsvpapp/master/static/cloudyuga.png",
)
COMPANY = os.environ.get('COMPANY', "CloudYuga Technology Pvt. Ltd.")
MONGODB_URI = os.environ.get(
    'MONGODB_URI', 'mongodb://localhost:27017/rsvpdata'
)
client = MongoClient(MONGODB_URI)
db = client.get_default_database()
connect(MONGODB_URI)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.session_protection = "strong"


def format_date(value):
    try:
        return datetime.datetime.strptime(value, '%Y-%m-%d').strftime(
            "%a, %d %b '%y"
        )

    except ValueError:
        return value


def random_id():
    return ObjectId(
        bytes(
            ''.join(choice(string.ascii_letters) for _ in range(12)), 'ascii'
        )
    )


app.jinja_env.filters['format_date'] = format_date


@login_manager.user_loader
def load_user(user_id):
    print("loading user")
    return User.objects.raw({"_id": user_id}).first()


""" OAuth Session creation """


def get_google_auth(state=None, token=None):
    if token:
        return OAuth2Session(Auth.CLIENT_ID, token=token)

    if state:
        return OAuth2Session(
            Auth.CLIENT_ID, state=state, redirect_uri=Auth.REDIRECT_URI
        )

    oauth = OAuth2Session(
        Auth.CLIENT_ID, redirect_uri=Auth.REDIRECT_URI, scope=Auth.SCOPE
    )
    return oauth


@app.before_request
def redirect_heroku():
    """Redirect herokuapp requests to rsvp.thatteidlikaalsoup.team."""
    urlparts = urlparse(request.url)
    if urlparts.netloc == 'thatte-idli-rsvp.herokuapp.com':
        urlparts_list = list(urlparts)
        urlparts_list[1] = 'rsvp.thatteidlikaalsoup.team'
        return redirect(urlunparse(urlparts_list), code=301)


@app.route('/version-<version>/<path:static_file>')
def versioned_static(version, static_file):
    return send_file(static_file)


class RSVP(object):
    """Simple Model class for RSVP"""

    def __init__(self, name, email, event_id=None, _id=None):
        self.name = name
        self.email = email
        self._id = ObjectId(_id) if isinstance(_id, str) else _id
        self.event_id = ObjectId(event_id) if isinstance(
            event_id, str
        ) else event_id

    def dict(self):
        _id = str(self._id)
        event_id = self.event_id
        return {
            "_id": _id,
            "name": self.name,
            "email": self.email,
            "links": {
                "self": "{}api/rsvps/{}/{}".format(
                    request.url_root, event_id, _id
                )
            },
        }

    def delete(self):
        db.events.find_one_and_update(
            {'_id': self.event_id}, {'$pull': {'rsvps': {'_id': self._id}}}
        )

    @staticmethod
    def find_all(event_id):
        event = db.events.find_one({'_id': ObjectId(event_id)})
        return [] if event is None or 'rsvps' not in event else [
            RSVP(event_id=event_id, **doc) for doc in event.get('rsvps', [])
        ]

    @staticmethod
    def find_one(event_id, rsvp_id):
        _id = ObjectId(rsvp_id)
        event = db.events.find_one(
            {'_id': ObjectId(event_id)},
            {'rsvps': {'$elemMatch': {'_id': _id}}},
        )
        if event is None or 'rsvps' not in event:
            return

        doc = event['rsvps'][0]
        return RSVP(doc['name'], doc['email'], event_id, doc['_id'])

    @staticmethod
    def new(name, email, event_id):
        doc = {"name": name, "email": email, "_id": random_id()}
        result = db.events.find_one_and_update(
            {'_id': ObjectId(event_id)}, {'$push': {'rsvps': doc}}
        )
        assert result is not None, "Event does not exist"
        return RSVP(name, email, event_id, str(doc['_id']))


class User(MongoModel):
    email = fields.EmailField(primary_key=True)
    name = fields.CharField()
    active = fields.CharField()
    tokens = fields.CharField()

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return self.email

    def toJSON(self):
        return json.dumps(
            self, default=self.__dict__, sort_keys=True, indent=4
        )

    @staticmethod
    def new(self):
        result = db['user'].insert_one(self.toJSON())
        return result

    @staticmethod
    def get_by_email(email):
        return db['user'].find_one({"email": email})

    @staticmethod
    def get_by_id(id):
        return db['user'].find_one({"_id": id})

    def set_tokens(self, tokens):
        self.tokens = tokens


@app.route('/')
@login_required
def index():
    today = datetime.date.today().strftime('%Y-%m-%d')
    upcoming_events = list(
        db.events.find({'date': {"$gte": today}}, sort=[('date', ASCENDING)])
    )
    archived_events = list(
        db.events.find({'date': {"$lt": today}}, sort=[('date', DESCENDING)])
    )
    count = len(upcoming_events)
    return render_template(
        'index.html',
        count=count,
        upcoming_events=upcoming_events,
        archived_events=archived_events,
        TEXT1=TEXT1,
        LOGO=LOGO,
        COMPANY=COMPANY,
    )


@app.route('/event/<id>', methods=['GET'])
def event(id):
    event = db.events.find_one({"_id": ObjectId(id)})
    rsvps = event.get('rsvps', [])
    count = len(rsvps)
    event_text = '{} - {}'.format(event['name'], format_date(event['date']))
    description = 'Call in for {}'.format(event_text)
    return render_template(
        'event.html',
        count=count,
        event=event,
        items=rsvps,
        TEXT1=TEXT1,
        TEXT2=event_text,
        description=description,
        LOGO=LOGO,
        COMPANY=COMPANY,
    )


@app.route('/new/<event_id>', methods=['POST'])
def new(event_id):
    name = request.form['name']
    email = 'email@example.com'
    if name:
        RSVP.new(name, email, event_id)
    return redirect(url_for('event', id=event_id))


@app.route('/event', methods=['POST'])
def create_event():
    item_doc = {'name': request.form['name'], 'date': request.form['date']}
    if item_doc['name'] and item_doc['date']:
        db.events.insert_one(item_doc)
    return redirect(url_for('index'))


# FIXME: Add POST method
@app.route('/api/events/', methods=['GET'])
def api_events():
    return json.dumps(
        [
            dict(_id=str(event['_id']), name=event['name'], date=event['date'])
            for event in db.events.find()
        ],
        indent=True,
    )


@app.route('/api/rsvps/<event_id>', methods=['GET', 'POST'])
def api_rsvps(event_id):
    if request.method == 'GET':
        docs = [rsvp.dict() for rsvp in RSVP.find_all(event_id)]
        return json.dumps(docs, indent=True)

    else:
        try:
            doc = json.loads(request.data)
        except ValueError:
            return '{"error": "expecting JSON payload"}', 400

        if 'name' not in doc:
            return '{"error": "name field is missing"}', 400

        if 'email' not in doc:
            return '{"error": "email field is missing"}', 400

        rsvp = RSVP.new(doc['name'], doc['email'], event_id)
        return json.dumps(rsvp.dict(), indent=True)


@app.route('/api/rsvps/<event_id>/<rsvp_id>', methods=['GET', 'DELETE'])
def api_rsvp(event_id, rsvp_id):
    rsvp = RSVP.find_one(event_id, rsvp_id)
    if not rsvp:
        return json.dumps({"error": "not found"}), 404

    if request.method == 'GET':
        return json.dumps(rsvp.dict(), indent=True)

    elif request.method == 'DELETE':
        rsvp.delete()
        return json.dumps({"deleted": "true"})


@app.route('/login')
def login():
    print("log in")
    print(current_user.is_authenticated)
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    print("here a")
    google = get_google_auth()
    print("here b")
    auth_url, state = google.authorization_url(
        Auth.AUTH_URI, access_type='offline'
    )
    print("here c")
    session['oauth_state'] = state
    print("here d")
    return render_template('login.html', auth_url=auth_url)


@app.route('/oauth2callback')
def callback():
    print("here")
    if current_user is not None and current_user.is_authenticated:
        return redirect(url_for('index'))

    if 'error' in request.args:
        if request.args.get('error') == 'access_denied':
            return 'You denied access.'

        return 'Error encountered.'

    if 'code' not in request.args and 'state' not in request.args:
        return redirect(url_for('login'))

    else:
        google = get_google_auth(state=session['oauth_state'])
        try:
            token = google.fetch_token(
                Auth.TOKEN_URI,
                client_secret=Auth.CLIENT_SECRET,
                authorization_response=request.url,
            )
        except HTTPError:
            return 'HTTPError occurred.'

        google = get_google_auth(token=token)
        resp = google.get(Auth.USER_INFO)
        if resp.status_code == 200:
            user_data = resp.json()
            email = user_data['email']
            print(user_data)
            print(email)
            user = User.objects.raw({"_id": email})
            # print(json.dumps(user))
            if user is None:
                user = User(email)
                print("made new one")
            else:
                user = user.first()
            # user.name = user_data['name']
            user.set_tokens(json.dumps(token))
            print("type is ")
            print(type(user))
            user.save()
            login_user(user)
            print("Redirecting to index")
            return redirect(url_for('index'))

        return 'Could not fetch your information.'


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


if __name__ == '__main__':
    DEBUG = 'DEBUG' in os.environ
    if DEBUG:
        app.jinja_env.cache = None
    app.run(host='0.0.0.0', debug=DEBUG)
