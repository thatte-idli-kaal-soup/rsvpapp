import datetime
import json
import os

from bson.objectid import ObjectId
from flask import Flask, render_template, redirect, url_for, request, make_response
from pymongo import MongoClient, ASCENDING, DESCENDING

app = Flask(__name__)
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


class RSVP(object):
    """Simple Model class for RSVP"""

    def __init__(self, name, email, event_id=None, _id=None):
        self.name = name
        self.email = email
        self._id = _id
        self.event_id = event_id

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
        db['event-{}'.format(self.event_id)].find_one_and_delete(
            {"_id": self._id}
        )

    @staticmethod
    def find_all(event_id):
        return [
            RSVP(event_id=event_id, **doc)
            for doc in db['event-{}'.format(event_id)].find()
        ]

    @staticmethod
    def find_one(event_id, rsvp_id):
        doc = db['event-{}'.format(event_id)].find_one(
            {"_id": ObjectId(rsvp_id)}
        )
        return doc and RSVP(doc['name'], doc['email'], event_id, doc['_id'])

    @staticmethod
    def new(name, email, event_id):
        doc = {"name": name, "email": email}
        result = db['event-{}'.format(event_id)].insert_one(doc)
        return RSVP(name, email, event_id, result.inserted_id)


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
    items = list(db['event-{}'.format(id)].find())
    count = len(items)
    return render_template(
        'event.html',
        count=count,
        event=event,
        items=items,
        TEXT1=TEXT1,
        TEXT2='{} - {}'.format(event['name'], event['date']),
        LOGO=LOGO,
        COMPANY=COMPANY,
    )


@app.route('/new/<id>', methods=['POST'])
def new(id):
    item_doc = {'name': request.form['name'], 'email': 'email@example.com'}
    if item_doc['name'] and item_doc['email']:
        db['event-{}'.format(id)].insert_one(item_doc)
    return redirect(url_for('event', id=id))


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


@app.route('/api/rsvps/<id>', methods=['GET', 'POST'])
def api_rsvps(id):
    if request.method == 'GET':
        docs = [rsvp.dict() for rsvp in RSVP.find_all(id)]
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

        rsvp = RSVP.new(name=doc['name'], email=doc['email'], event_id=id)
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
    app.run(host='0.0.0.0', debug=True)
