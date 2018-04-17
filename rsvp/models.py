import datetime

from flask_login import UserMixin
from flask_mongoengine import MongoEngine

from .utils import random_id

db = MongoEngine()


class RSVP(db.EmbeddedDocument):
    id = db.ObjectIdField(default=random_id, primary_key=True)
    name = db.StringField(unique=True)
    note = db.StringField()
    date = db.DateTimeField(required=True, default=datetime.datetime.now)
    rsvp_by = db.LazyReferenceField('User')


class Event(db.Document):
    rsvps = db.EmbeddedDocumentListField(RSVP)
    name = db.StringField(required=True)
    date = db.DateTimeField(required=True)
    archived = db.BooleanField(required=True, default=False)
    created_by = db.LazyReferenceField('User')
    cancelled = db.BooleanField(required=True, default=False)


class User(db.Document, UserMixin):
    email = db.EmailField(primary_key=True)
    name = db.StringField()
    active = db.BooleanField(default=True)
    upi_id = db.StringField()
    blood_group = db.StringField()
    nick = db.StringField()
    dob = db.DateTimeField()

    def get_id(self):
        return self.email
