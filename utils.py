import datetime
from random import choice
import string

from bson.objectid import ObjectId


def format_date(value):
    try:
        format = "%a, %d %b '%y, %H:%M" if value.hour != 0 or value.minute != 0 else "%a, %d %b '%y"
        return value.strftime(format)

    except ValueError:
        return value


def random_id():
    return ObjectId(
        bytes(
            ''.join(choice(string.ascii_letters) for _ in range(12)), 'ascii'
        )
    )


def rsvp_by(rsvp):
    return rsvp.rsvp_by.fetch().name if rsvp.rsvp_by else 'Anonymous'
