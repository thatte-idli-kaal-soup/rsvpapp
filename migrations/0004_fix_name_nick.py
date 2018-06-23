import re

aliases = {'Ani': ''}


def up(db):
    for user in db.user.find():
        nick = user.get('nick')
        if nick and nick.strip() != nick:
            print(repr(nick), repr(nick.strip()))
            db.user.find_one_and_update(
                {'_id': user['_id']}, {'$set': {'nick': nick.strip()}}
            )


def down(db):
    pass
