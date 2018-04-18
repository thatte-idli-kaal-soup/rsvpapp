import datetime
import os
import sys

import click
import mongoengine.errors
from mongoengine.queryset.visitor import Q

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import User
from rsvp import app
from utils import format_date


@click.group()
def cli():
    """A CLI to manage events"""
    pass


@click.command()
@click.option('--roles', type=str)
@click.option('--users', type=str,default='')
@click.option('--all', default=False,is_flag=True)
def add_role(roles,users, all):
    """Archive old events."""
    click.echo('Adding role')
    print(roles)
    roles=roles.split(',')
    for role in roles:
        if all:
            User.objects(roles__nin=[role]).update(push__roles=roles)
        else:
            for user in users.split(','):
                print(user)
                User.objects(Q(email=user) & Q(roles__nin=[role])).update(push__roles=roles)



    # with app.test_request_context():
    #     today = datetime.datetime.now()
    #     upcoming_events = Event.objects.filter(date__gte=today).order_by(
    #         'date'
    #     )
    #     archived_events = Event.objects.filter(date__lt=today).order_by(
    #         '-date'
    #     )
    #     upcoming_events.update(archived=False)
    #     archived_events.update(archived=True)



cli.add_command(add_role)
if __name__ == '__main__':
    cli()
