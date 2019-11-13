import datetime

from flask_login import UserMixin, AnonymousUserMixin
from flask_mongoengine import MongoEngine
from mongoengine import signals

from .utils import random_id, markdown_to_html, read_app_config
from .zulip_utils import zulip_announce_event, zulip_announce_post


db = MongoEngine()
ANONYMOUS_EMAIL = "anonymous@example.com"


class Team(db.Document):
    slug = db.StringField(primary_key=True)
    name = db.StringField()


class Role(db.EmbeddedDocument):
    name = db.StringField()
    team = db.LazyReferenceField("Team")


class RSVP(db.EmbeddedDocument):
    id = db.ObjectIdField(default=random_id, primary_key=True)
    user = db.LazyReferenceField("User", unique=True)
    note = db.StringField()
    date = db.DateTimeField(required=True, default=datetime.datetime.now)
    rsvp_by = db.LazyReferenceField("User")
    cancelled = db.BooleanField(default=False)
    waitlisted = db.BooleanField(default=False)

    def can_cancel(self, user):
        return (
            user == self.rsvp_by or user == self.user or self.rsvp_by is None
        )

    @property
    def sort_attributes(self):
        return (self.cancelled, self.waitlisted, self.date)


class Event(db.Document):
    rsvps = db.EmbeddedDocumentListField(RSVP)
    rsvp_limit = db.IntField(default=0)
    name = db.StringField(required=True)
    description = db.StringField()
    html_description = db.StringField()
    # FIXME: Should be called start_date
    date = db.DateTimeField(required=True)
    _end_date = db.DateTimeField()
    archived = db.BooleanField(required=True, default=False)
    created_by = db.LazyReferenceField("User")
    cancelled = db.BooleanField(required=True, default=False)
    splitwise_group_id = db.StringField()
    meta = {"indexes": [{"fields": ["$name", "$description"]}]}  # text index

    @classmethod
    def pre_save(cls, sender, document, **kwargs):
        document.html_description = markdown_to_html(document.description)

    @property
    def active_rsvps(self):
        return sorted(
            self.rsvps.filter(cancelled=False, waitlisted=False),
            key=lambda x: x.sort_attributes,
        )

    @property
    def all_rsvps(self):
        return sorted(self.rsvps, key=lambda x: x.sort_attributes)

    @property
    def end_date(self):
        if self._end_date is not None:
            return self._end_date
        config = read_app_config()
        duration = config["EVENT_DURATION"]
        return self.date + datetime.timedelta(seconds=duration)

    @property
    def non_cancelled_rsvps(self):
        return sorted(
            self.rsvps.filter(cancelled=False), key=lambda x: x.sort_attributes
        )

    @property
    def rsvp_count(self):
        return len(self.active_rsvps)

    def can_edit(self, user):
        return user.is_admin or (
            self.created_by and self.created_by.fetch().email == user.email
        )

    def can_rsvp(self, user):
        return user.is_admin or not (self.archived or self.cancelled)

    def update_waitlist(self):
        for i, rsvp in enumerate(self.non_cancelled_rsvps):
            rsvp.waitlisted = (
                i >= self.rsvp_limit if self.rsvp_limit > 0 else False
            )
        self.save()


signals.pre_save.connect(Event.pre_save, sender=Event)
signals.post_save.connect(zulip_announce_event, sender=Event)


class User(db.Document, UserMixin):
    email = db.EmailField(primary_key=True)
    name = db.StringField()
    gender = db.StringField()
    active = db.BooleanField(default=True)
    upi_id = db.StringField()
    splitwise_id = db.StringField()
    blood_group = db.StringField()
    nick = db.StringField()
    dob = db.DateTimeField()
    hide_dob = db.BooleanField(default=False)
    roles = db.EmbeddedDocumentListField(Role)

    def get_id(self):
        return self.email

    def has_role(self, role):
        return role in {r.name for r in self.roles}

    def has_any_role(self, *roles):
        for role in roles:
            if self.has_role(role):
                return True
        return False

    def add_to_team(self, team_slug):
        self.add_role_in_team(team_slug, ".approved-user")

    def add_role_in_team(self, team_slug, role_name):
        role = Role(name=role_name, team=team_slug)
        self.roles.append(role)
        self.save()

    @property
    def is_approved(self):
        return self.has_role(".approved-user")

    @staticmethod
    def approved_users():
        return User.objects.filter(roles__name__in=[".approved-user"]).all()

    @staticmethod
    def pending_approval_users():
        return User.objects.filter(roles__name__nin=[".approved-user"]).all()

    @staticmethod
    def admins():
        return User.objects.filter(roles__name__in=["admin"]).all()

    @property
    def visible_roles(self):
        return [r for r in self.roles if not r.name.startswith(".")]

    @property
    def is_admin(self):
        return self.has_role("admin")

    @property
    def is_anonymous_user(self):
        return self.email == ANONYMOUS_EMAIL


class AnonymousUser(AnonymousUserMixin):
    email = None

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
    authors = db.ListField(db.ReferenceField("User"))
    public = db.BooleanField(default=False)
    draft = db.BooleanField(default=False)

    @classmethod
    def pre_save(cls, sender, document, **kwargs):
        # If a document is a draft, turn off the public flag
        if document.draft:
            document.public = False
        document.html_content = markdown_to_html(document.content)

    def can_edit(self, user):
        return user.is_admin or (user.email in {a.id for a in self.authors})

    def list_authors(self):
        names = []
        for author in self.authors:
            names.append(author.nick or author.name)
        names = ", ".join(names)
        return " & ".join(names.rsplit(",", 1))


signals.pre_save.connect(Post.pre_save, sender=Post)
signals.post_save.connect(zulip_announce_post, sender=Post)


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
