def up(db):
    for user in db.user.find():
        print(user)
        if 'tokens' not in user:
            continue

        db.user.find_one_and_update(
            {'_id': user['_id']}, {'$unset': {'tokens': ''}}
        )
    for user in db.user.find():
        assert 'tokens' not in user


def down(db):
    pass
