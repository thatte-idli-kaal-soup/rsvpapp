import os
from pymongo import MongoClient

MONGODB_URI = os.environ.get(
    'MONGODB_URI', 'mongodb://localhost:27017/rsvpdata'
)
client = MongoClient(MONGODB_URI)
db = client.get_default_database()
# Find all events and update them
for event in db.events.find():
    _id = event['_id']
    event_id = 'event-{}'.format(_id)
    rsvps = list(db[event_id].find())
    if 'rsvps' not in event:
        print('Updating event {}'.format(_id))
        db.events.update({'_id': _id}, {'$set': {'rsvps': rsvps}})
        event = db.events.find_one({'_id': _id})
        assert len(event['rsvps']) == len(rsvps), 'Incorrectly migrated'
    db[event_id].drop()
