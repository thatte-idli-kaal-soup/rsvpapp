import re

aliases = {'Ani': ''}
aliases = {
    'Birdie': 'Arvind S',
    'Pranav Gopinath': 'Pranav G',
    'Aishwarya Ashoka': 'Aishwarya Ashok',
    'Akhil': '',
    'Mikhail': '',
    'Vinuth G m': 'vinuth gm',
    'Hippo': 'Meghana Iyer',
    'Sampu': 'sampath jayaram',
    'Vinits': 'VINIT SUBHAS GULASHETTI',
    'saru': 'sarvani muppane',
    'Mohamed Saqlain CK': 'Mohamed Saqlain',
    'Poba': 'bharath jb',
    'Xxxxxx': '',
    'Venky': 'Venkatesh S',
    'Daadi': '',
    'Saru': 'sarvani muppane',
    'Shyam': '',
    'Rusha': '',
    'Sarvani m p': 'sarvani muppane',
    'Arvind Philipose': '',
    'Rum': 'ramya kat',
    'Ramya Shree A': 'ramya kat',
    'Boba': 'Dinesh Gogula',
    'Wembar': 'Arvind S',
    'Rajjan': 'Aditya Rajan',
    'Syed Daanish Suhail': 'Daanish Suhail',
    'Yogi': 'Yogesh B M',
    'Meghana B': 'Meghana Iyer',
}


def up(db):
    # Create anonymous user
    anonymous_user = db.user.find_one({'_id': 'anonymous@example.com'})
    if not anonymous_user:
        anonymous_user = db.user.insert(
            {'_id': 'anonymous@example.com', 'name': 'Unknown User'}
        )
    anonymous_user = db.user.find_one({'_id': 'anonymous@example.com'})
    for event in db.event.find():
        for rsvp in event['rsvps']:
            # Remove rsvp
            db.event.find_one_and_update(
                {'_id': event['_id']},
                {'$pull': {'rsvps': {'_id': rsvp['_id']}}},
            )
            # Figure out user
            name = rsvp.pop('name').strip()
            name = re.sub('[^A-Za-z\s]', '', name).strip()
            query = [
                {'name': name},
                {'nick': name},
                {'name': name.lower()},
                {'nick': name.lower()},
            ]
            alias = aliases.get(name)
            if alias:
                query.append({'name': alias})
            user = db.user.find_one({'$or': query})
            if not user:
                user = db.user.find_one(
                    {
                        '$or': [
                            {
                                'name': {
                                    '$regex': '{}.*'.format(name),
                                    '$options': 'i',
                                }
                            }
                        ]
                    }
                )
            # Add new rsvp
            if not user:
                user = anonymous_user
                rsvp['note'] = '{}: {}'.format(name, rsvp.get('note', ''))
            rsvp['user'] = user['_id']
            db.event.find_one_and_update(
                {'_id': event['_id']}, {'$push': {'rsvps': rsvp}}
            )


def down(db):
    pass
