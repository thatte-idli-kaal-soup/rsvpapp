import datetime

from flask_login import UserMixin, AnonymousUserMixin
from flask_mongoengine import MongoEngine
from mongoengine import signals

from .utils import random_id, markdown_to_html, read_app_config, format_date
from .zulip_utils import zulip_announce_event, zulip_announce_post


db = MongoEngine()
ANONYMOUS_EMAIL = "anonymous@example.com"


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


class PickUpTeam(db.EmbeddedDocument):
    id = db.ObjectIdField(default=random_id, primary_key=True)
    name = db.StringField(required=True)
    rsvp_ids = db.ListField(db.ObjectIdField())

    def add_rsvp(self, rsvp_id):
        self.rsvp_ids.append(rsvp_id)


class Event(db.Document):
    rsvps = db.EmbeddedDocumentListField(RSVP)
    rsvp_limit = db.IntField(default=0)
    name = db.StringField(required=True)
    description = db.StringField()
    html_description = db.StringField()
    pickup_teams = db.EmbeddedDocumentListField(PickUpTeam)
    # FIXME: Should be called start_date
    date = db.DateTimeField(required=True)
    _end_date = db.DateTimeField()
    archived = db.BooleanField(required=True, default=False)
    created_by = db.LazyReferenceField("User")
    cancelled = db.BooleanField(required=True, default=False)
    splitwise_group_id = db.StringField()
    gdrive_id = db.StringField()
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

    @property
    def title(self):
        return "{} - {}".format(self.name, format_date(self.date))

    @property
    def male_rsvps(self):
        return self.rsvps_with_gender("male")

    @property
    def female_rsvps(self):
        return self.rsvps_with_gender("female")

    def form_pickup_teams(self):
        # FIXME: Fixed number of teams.
        if len(self.pickup_teams) == 0:
            Black = PickUpTeam(name="Black")
            White = PickUpTeam(name="White")
            self.pickup_teams = [Black, White]

    def add_rsvp_to_pickup_team(self, rsvp):
        user = rsvp.user.fetch()
        if user.gender == "male":
            if len(self.male_rsvps) % 2:
                self.pickup_teams[0].add_rsvp(rsvp.id)
            else:
                self.pickup_teams[1].add_rsvp(rsvp.id)
        elif user.gender == "female":
            if len(self.female_rsvps) % 2:
                self.pickup_teams[0].add_rsvp(rsvp.id)
            else:
                self.pickup_teams[1].add_rsvp(rsvp.id)
        else:
            # Try to handle users with unknown genders by pick up team size
            if len(self.pickup_teams[0].rsvp_ids) <= len(
                self.pickup_teams[1].rsvp_ids
            ):
                self.pickup_teams[0].add_rsvp(rsvp.id)
            else:
                self.pickup_teams[1].add_rsvp(rsvp.id)

    def rsvps_with_gender(self, gender):
        return [
            r for r in self.active_rsvps if r.user.fetch().gender == gender
        ]

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
    phone = db.StringField()
    address = db.StringField()
    hide_dob = db.BooleanField(default=False)
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

    @classmethod
    def published_posts(cls):
        return Post.objects.filter(draft=False)

    @classmethod
    def public_posts(cls):
        return cls.objects.filter(draft=False, public=True)


signals.pre_save.connect(Post.pre_save, sender=Post)
signals.post_save.connect(zulip_announce_post, sender=Post)


class GDrivePhoto(db.Document):
    gdrive_id = db.StringField(required=True)
    gdrive_thumbnail = db.URLField(required=True)
    gdrive_parent = db.StringField(required=True)
    gdrive_path = db.StringField(required=True)
    gdrive_metadata = db.DictField()
    gdrive_created_at = db.DateTimeField(required=True)

    @classmethod
    def new_photos(cls, n=2):
        days = datetime.datetime.now() - datetime.timedelta(days=n)
        return cls.objects.filter(gdrive_created_at__gte=days)


class Bookmark(db.Document):
    url = db.URLField(required=True)
    title = db.StringField()
    description = db.StringField()
    image = db.URLField()


class InterestedUser(db.Document):
    created_at = db.DateTimeField(required=True, default=datetime.datetime.now)
    email = db.EmailField()
