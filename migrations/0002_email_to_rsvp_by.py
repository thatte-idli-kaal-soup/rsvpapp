import os
import sys

from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MONGODB_URI = os.environ.get(
    'MONGODB_URI', 'mongodb://localhost:27017/rsvpdata'
)
client = MongoClient(MONGODB_URI)
db = client.get_default_database()


def up(_):
    for event in db.event.find():
        for rsvp in event['rsvps']:
            if 'email' not in rsvp:
                continue

            db.event.find_one_and_update(
                {'_id': event['_id']},
                {'$pull': {'rsvps': {'_id': rsvp['_id']}}},
            )
            email = rsvp.pop('email', None)
            anonymous_emails = {
                'email@example.com', 'test@example.com', 'anonymous@user.com'
            }
            rsvp['rsvp_by'] = email if email not in anonymous_emails else None
            db.event.find_one_and_update(
                {'_id': event['_id']}, {'$push': {'rsvps': rsvp}}
            )


def down(_):
    for event in db.event.find():
        print(event)
        for rsvp in event['rsvps']:
            if 'rsvp_by' not in rsvp:
                continue

            db.event.find_one_and_update(
                {'_id': event['_id']},
                {'$pull': {'rsvps': {'_id': rsvp['_id']}}},
            )
            rsvp['email'] = rsvp.pop('rsvp_by', None) or 'email@example.com'
            db.event.find_one_and_update(
                {'_id': event['_id']}, {'$push': {'rsvps': rsvp}}
            )
