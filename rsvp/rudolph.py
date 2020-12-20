#!/usr/bin/env python3

from datetime import datetime
import random

from flask import render_template

from rsvp.models import Event, User
from rsvp.utils import send_email


YEAR = datetime.now().year
SENDER = "Fun Committee, TIKS"
SUBJECT = "TIKS Secret Santa {}".format(YEAR)
HEADERS = """\
From: {from} <{from_id}>\r
To: {santa} <{santa_id}>\r
Subject: {subject}\r
\r
"""


def get_people(event_id):
    """Reads list of participants from ../data/secret-santa.csv

    The CSV file needs to have column headers and a column named 'Email'. The
    first column MUST be the names of the participants.

    """
    event = Event.objects.get(id=event_id)
    return [rsvp.user.fetch() for rsvp in event.active_rsvps]


def is_good_pairing(pairs):
    """Function to test if a pairing is valid."""
    santas = set()
    kiddos = set()

    for santa, kiddo in pairs:
        if santa == kiddo:
            return False
        santas.add(santa)
        kiddos.add(kiddo)

    return len(santas) == len(kiddos) == len(list(pairs))


def pick_pairs(people):
    """Pick pairs from a list of users."""
    n = len(people)
    m = n // 2
    names = [person.email for person in people]
    # Shuffle the names
    santas = random.sample(names, n)
    # Split the shuffled names into two halves and assign kiddos from 'other'
    # halves.  Shuffle the santa names, before assignment.
    m_ = n - m
    santas_1, santas_2 = (
        random.sample(santas[:m], m),
        random.sample(santas[m:], m_),
    )
    kiddos_1, kiddos_2 = santas[m_:], santas[:m_]
    return list(zip(santas_1, kiddos_1)) + list(zip(santas_2, kiddos_2))


def persist_pairs(pairs):
    """Just print pairs to the terminal."""
    for (santa, kiddo) in pairs:
        print("{} -- {}".format(santa, kiddo))


def notify_santas(pairs, test=True):
    for santa, kiddo in pairs:
        santa = User.objects.get(email=santa)
        kiddo = User.objects.get(email=kiddo)
        content = render_template(
            "secret-santa.txt",
            santa_name=(santa.nick or santa.name),
            kiddo_name=(kiddo.nick or kiddo.name),
            kiddo=kiddo,
            from_=SENDER,
        )
        if not test:
            send_email([santa], SUBJECT, content)
        else:
            print(content)


def main(people, test=True):
    good_pairs = False
    while not good_pairs:
        pairs = pick_pairs(people)
        good_pairs = is_good_pairing(pairs)
    persist_pairs(pairs)
    notify_santas(pairs, test=test)
    return pairs
