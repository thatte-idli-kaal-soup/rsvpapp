import datetime

from flask_mongoengine import MongoEngine

from utils import random_id

db = MongoEngine()


class RSVP(db.EmbeddedDocument):
    id = db.ObjectIdField(default=random_id, primary_key=True)
    name = db.StringField(unique=True)
    email = db.EmailField()
    note = db.StringField()
    date = db.DateTimeField(required=True, default=datetime.datetime.now)


class Event(db.Document):
    rsvps = db.EmbeddedDocumentListField(RSVP)
    name = db.StringField(required=True)
    date = db.DateTimeField(required=True)
    archived = db.BooleanField(required=True, default=False)


class User(db.Document):
    email = db.EmailField(primary_key=True)
    name = db.StringField()
    active = db.BooleanField(default=True)
    tokens = db.StringField()

    @property
    def is_authenticated(self):
        return True

    def is_active(self):
        return self.active

    def is_anonymous(self):
        return False

    def get_id(self):
        return self.email

    def set_tokens(self, tokens):
        self.tokens = tokens
        self.save()
