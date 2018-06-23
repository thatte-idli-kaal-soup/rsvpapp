import datetime

from flask_login import UserMixin, AnonymousUserMixin
from flask_mongoengine import MongoEngine
from mongoengine import signals

from .utils import random_id, markdown_to_html

db = MongoEngine()


class RSVP(db.EmbeddedDocument):
    id = db.ObjectIdField(default=random_id, primary_key=True)
    user = db.LazyReferenceField('User', unique=True)
    note = db.StringField()
    date = db.DateTimeField(required=True, default=datetime.datetime.now)
    rsvp_by = db.LazyReferenceField('User')


class Event(db.Document):
    rsvps = db.EmbeddedDocumentListField(RSVP)
    name = db.StringField(required=True)
    description = db.StringField()
    html_description = db.StringField()
    date = db.DateTimeField(required=True)
    archived = db.BooleanField(required=True, default=False)
    created_by = db.LazyReferenceField('User')
    cancelled = db.BooleanField(required=True, default=False)

    @classmethod
    def pre_save(cls, sender, document, **kwargs):
        document.html_description = markdown_to_html(document.description)


signals.pre_save.connect(Event.pre_save, sender=Event)


class User(db.Document, UserMixin):
    email = db.EmailField(primary_key=True)
    name = db.StringField()
    gender = db.StringField()
    active = db.BooleanField(default=True)
    upi_id = db.StringField()
    blood_group = db.StringField()
    nick = db.StringField()
    dob = db.DateTimeField()
    roles = db.SortedListField(db.StringField())

    def get_id(self):
        return self.email

    def has_role(self, role):
        return role in self.roles

    def has_any_role(self, *roles):
        for role in roles:
            if role in self.roles:
                return True

        return False

    @staticmethod
    def approved_users():
        return User.objects.filter(roles__in=['.approved-user']).all()


class AnonymousUser(AnonymousUserMixin):

    def has_role(self, role):
        return False

    def has_any_role(self, *args):
        return False
