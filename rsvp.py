import datetime
import json
import os
from random import choice
import string
from urllib.parse import urlparse, urlunparse

from bson.objectid import ObjectId
from flask import Flask, render_template, redirect, url_for, request, send_file
from flaskext.versioned import Versioned
from pymongo import MongoClient, ASCENDING, DESCENDING

app = Flask(__name__)
versioned = Versioned(app)
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


@app.route('/')
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


if __name__ == '__main__':
    DEBUG = 'DEBUG' in os.environ
    if DEBUG:
        app.jinja_env.cache = None
    app.run(host='0.0.0.0', debug=DEBUG)
