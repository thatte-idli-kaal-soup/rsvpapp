from flask_mongoengine import MongoEngine

from utils import random_id

db = MongoEngine()


class RSVP(db.EmbeddedDocument):
    id = db.ObjectIdField(default=random_id, primary_key=True)
    name = db.StringField(unique=True)
    email = db.EmailField()
    note = db.StringField()


class Event(db.Document):
    rsvps = db.EmbeddedDocumentListField(RSVP)
    name = db.StringField(required=True)
    date = db.DateTimeField(required=True)
