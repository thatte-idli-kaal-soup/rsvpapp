import datetime

from flask import url_for
from flask_login import UserMixin, AnonymousUserMixin
from flask_mongoengine import MongoEngine
from mongoengine import signals

from .splitwise_utils import (
    calculate_dues,
    get_simplified_debts,
    get_groups,
    get_friends,
    sync_rsvps_with_splitwise_group,
    ensure_splitwise_ids_hook,
    splitwise_create_group_hook,
    SPLITWISE_DUES_LIMIT,
)
from .utils import random_id, markdown_to_html, read_app_config, format_date
from .zulip_utils import zulip_announce_event, zulip_announce_post


db = MongoEngine()
ANONYMOUS_EMAIL = "anonymous@example.com"


class RSVP(db.EmbeddedDocument):
    id = db.ObjectIdField(default=random_id, primary_key=True)
    user = db.LazyReferenceField("User", unique=False)
    note = db.StringField()
    date = db.DateTimeField(required=True, default=datetime.datetime.now)
    rsvp_by = db.LazyReferenceField("User")
    cancelled = db.BooleanField(default=False)
    waitlisted = db.BooleanField(default=False)

    def can_cancel(self, user):
        return user == self.rsvp_by or user == self.user or self.rsvp_by is None

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
    is_paid = db.BooleanField(required=True, default=False)
    splitwise_group_id = db.IntField()
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

    @property
    def url(self):
        return url_for("event", id=self.id)

    def rsvps_with_gender(self, gender):
        return [r for r in self.active_rsvps if r.user.fetch().gender == gender]

    def can_edit(self, user):
        return user.is_admin or (
            self.created_by and self.created_by.fetch().email == user.email
        )

    def can_rsvp(self, user):
        if user.is_admin:
            return True

        if self.is_paid:
            return user.splitwise_connected and user.acceptable_dues

        if not self.is_paid:
            return not (self.archived or self.cancelled)

        return False

    def update_waitlist(self):
        for i, rsvp in enumerate(self.non_cancelled_rsvps):
            rsvp.waitlisted = i >= self.rsvp_limit if self.rsvp_limit > 0 else False
        self.save()

    def sync_rsvps_with_splitwise(self):
        group_id = self.splitwise_group_id
        if not group_id:
            return True

        groups = get_groups(force_refresh=True)
        filtered_groups = [group for group in groups if group["id"] == group_id]
        if not len(filtered_groups) == 1:
            return False
        users = [rsvp.user.fetch() for rsvp in self.active_rsvps]
        sync_rsvps_with_splitwise_group(filtered_groups[0], users)
        return True


signals.pre_save.connect(Event.pre_save, sender=Event)
signals.post_save.connect(zulip_announce_event, sender=Event)
signals.pre_save.connect(ensure_splitwise_ids_hook, sender=Event)
signals.post_save.connect(splitwise_create_group_hook, sender=Event)


class User(db.Document, UserMixin):
    email = db.EmailField(primary_key=True)
    name = db.StringField()
    gender = db.StringField()
    active = db.BooleanField(default=True)
    upi_id = db.StringField()
    splitwise_id = db.IntField()
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

    @property
    def nick_name(self):
        return self.nick or self.name

    @staticmethod
    def approved_users():
        return User.objects.filter(roles__in=[".approved-user"]).all()

    @property
    def is_admin(self):
        return "admin" in self.roles

    @property
    def is_anonymous_user(self):
        return self.email == ANONYMOUS_EMAIL

    @property
    def splitwise_connected(self):
        if not self.splitwise_id:
            return False

        friend_ids = {f["id"] for f in get_friends()}
        return self.splitwise_id in friend_ids

    @property
    def dues(self):
        if not self.splitwise_id:
            return 0

        return calculate_dues(self.splitwise_id)

    @property
    def acceptable_dues(self):
        dues, _ = self.dues
        return dues <= SPLITWISE_DUES_LIMIT

    @property
    def dues_details(self):
        if not self.splitwise_id:
            return []

        debts = get_simplified_debts(self.splitwise_id)

        owed_users = User.objects.filter(splitwise_id__in=[d["to"] for d in debts])
        owed_users = {user.splitwise_id: user for user in owed_users}

        group_ids = [d["group_id"] for d in debts]
        events = Event.objects.filter(splitwise_group_id__in=group_ids)
        events = {event.splitwise_group_id: event for event in events}

        for debt in debts:
            debt["to_user"] = owed_users.get(debt["to"])
            debt["event"] = events.get(debt["group_id"])

        return debts


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
            names.append(author.nick_name)
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
