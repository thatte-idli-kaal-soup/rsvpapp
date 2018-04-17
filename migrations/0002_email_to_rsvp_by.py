def up(db):
    for event in db.event.find():
        for rsvp in event.get('rsvps', []):
            if 'email' not in rsvp:
                continue

            db.event.find_one_and_update(
                {'_id': event['_id']},
                {'$pull': {'rsvps': {'_id': rsvp['_id']}}},
            )
            email = rsvp.pop('email', None)
            anonymous_emails = {
                'email@example.com', 'test@example.com', 'anonymous@user.com'
            }
            rsvp['rsvp_by'] = email if email not in anonymous_emails else None
            db.event.find_one_and_update(
                {'_id': event['_id']}, {'$push': {'rsvps': rsvp}}
            )


def down(db):
    for event in db.event.find():
        print(event)
        for rsvp in event.get('rsvps', []):
            if 'rsvp_by' not in rsvp:
                continue

            db.event.find_one_and_update(
                {'_id': event['_id']},
                {'$pull': {'rsvps': {'_id': rsvp['_id']}}},
            )
            rsvp['email'] = rsvp.pop('rsvp_by', None) or 'email@example.com'
            db.event.find_one_and_update(
                {'_id': event['_id']}, {'$push': {'rsvps': rsvp}}
            )
