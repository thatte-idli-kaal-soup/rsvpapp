import datetime

from flask_login import UserMixin, AnonymousUserMixin
from flask_mongoengine import MongoEngine
from mongoengine import signals

from .gdrive_utils import add_rsvp_event_post_save_hook
from .utils import random_id, markdown_to_html, zulip_announce


db = MongoEngine()
ANONYMOUS_EMAIL = "anonymous@example.com"


class RSVP(db.EmbeddedDocument):
    id = db.ObjectIdField(default=random_id, primary_key=True)
    user = db.LazyReferenceField("User", unique=True)
    note = db.StringField()
    date = db.DateTimeField(required=True, default=datetime.datetime.now)
    rsvp_by = db.LazyReferenceField("User")
    cancelled = db.BooleanField(default=False)


class Event(db.Document):
    rsvps = db.EmbeddedDocumentListField(RSVP)
    name = db.StringField(required=True)
    description = db.StringField()
    html_description = db.StringField()
    date = db.DateTimeField(required=True)
    archived = db.BooleanField(required=True, default=False)
    created_by = db.LazyReferenceField("User")
    cancelled = db.BooleanField(required=True, default=False)
    meta = {"indexes": [{"fields": ["$name", "$description"]}]}  # text index

    @classmethod
    def pre_save(cls, sender, document, **kwargs):
        document.html_description = markdown_to_html(document.description)

    @property
    def active_rsvps(self):
        return self.rsvps.filter(cancelled=False)

    @property
    def rsvp_count(self):
        return len(self.active_rsvps)


signals.pre_save.connect(Event.pre_save, sender=Event)
signals.post_save.connect(zulip_announce, sender=Event)
signals.post_save.connect(add_rsvp_event_post_save_hook, sender=Event)


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
        return User.objects.filter(roles__in=[".approved-user"]).all()

    @property
    def is_admin(self):
        return "admin" in self.roles


class AnonymousUser(AnonymousUserMixin):
    def has_role(self, role):
        return False

    def has_any_role(self, *args):
        return False

    @property
    def is_admin(self):
        return False


class Post(db.Document):
    title = db.StringField(required=True)
    content = db.StringField()
    html_content = db.StringField()
    created_at = db.DateTimeField(required=True, default=datetime.datetime.now)
    archived = db.BooleanField(default=False)
    author = db.LazyReferenceField("User")
    public = db.BooleanField(default=False)

    @classmethod
    def pre_save(cls, sender, document, **kwargs):
        document.html_content = markdown_to_html(document.content)


signals.pre_save.connect(Post.pre_save, sender=Post)


class GDrivePhoto(db.Document):
    gdrive_id = db.StringField(required=True)
    gdrive_parent = db.StringField(required=True)
    gdrive_path = db.StringField(required=True)
    gdrive_metadata = db.DictField()
    gdrive_created_at = db.DateTimeField(required=True)

    @classmethod
    def new_photos(cls, n=2):
        two_days = datetime.datetime.now() - datetime.timedelta(days=n)
        return cls.objects.filter(gdrive_created_at__gte=two_days)


class Bookmark(db.Document):
    url = db.URLField(required=True)
    title = db.StringField()
    description = db.StringField()
    image = db.URLField()
