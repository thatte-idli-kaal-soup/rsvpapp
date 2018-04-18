import datetime


def up(db):
    if 'events' not in db.collection_names():
        return

    db.events.rename('event', dropTarget=True)
    for event in db.event.find():
        if isinstance(event['date'], datetime.datetime):
            continue

        db.event.find_one_and_update(
            {'_id': event['_id']},
            {
                '$set': {
                    'date': datetime.datetime.strptime(
                        event['date'], '%Y-%m-%d'
                    )
                }
            },
        )


def down(db):
    db.event.rename('events', dropTarget=True)
