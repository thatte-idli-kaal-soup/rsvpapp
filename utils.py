import datetime
from random import choice
import string

from bson.objectid import ObjectId


def format_date(value):
    try:
        return value.strftime("%a, %d %b '%y")

    except ValueError:
        return value


def random_id():
    return ObjectId(
        bytes(
            ''.join(choice(string.ascii_letters) for _ in range(12)), 'ascii'
        )
    )
