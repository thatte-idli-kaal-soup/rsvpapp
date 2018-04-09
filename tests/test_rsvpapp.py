import datetime
import json

import mongoengine
import mongomock

import rsvp

URI = 'mongomock://localhost:27017/rsvpdata'
config = {'MONGODB_SETTINGS': {'host': URI}}
extensions = rsvp.app.extensions
connections = extensions['mongoengine'][rsvp.db]['conn']
connections.close()
mongoengine.connection.disconnect()
extensions.pop('mongoengine')
rsvp.db.init_app(rsvp.app, config)


class BaseTest:

    def setup_method(self, method):
        self.client = rsvp.app.test_client()
        with rsvp.app.test_request_context():
            connection = rsvp.db.connection
            connection.drop_database('rsvpdata')


class TestRSVPApp(BaseTest):

    def test_create_event(self):
        event_data = {'name': 'test_event', 'date': '2018-01-01'}
        response = self.client.post(
            '/event', data=event_data, follow_redirects=True
        )
        assert response.status_code == 200

    def test_rsvp(self):
        date = datetime.datetime.today().strftime('%Y-%m-%d')
        event_data = {'name': 'test_event', 'date': date}
        response = self.client.post(
            '/event', data=event_data, follow_redirects=True
        )
        response = self.client.get('/api/events', follow_redirects=True)
        events = json.loads(response.data)
        event_id = events[0]['_id']['$oid']
        user_data = {
            'name': 'test_name',
            'email': 'test_email@test_domain.com',
            'note': 'my awesome note',
        }
        response = self.client.post(
            '/new/{}'.format(event_id), data=user_data, follow_redirects=True
        )
        assert response.status_code == 200
        assert user_data['name'] in str(response.data)
        assert user_data['note'] in str(response.data)

    def test_rsvp_archived_doesnot_work(self):
        event_data = {'name': 'test_event', 'date': '2018-01-01'}
        response = self.client.post(
            '/event', data=event_data, follow_redirects=True
        )
        response = self.client.get('/api/events', follow_redirects=True)
        events = json.loads(response.data)
        event_id = events[0]['_id']['$oid']
        user_data = {
            'name': 'test_name',
            'email': 'test_email@test_domain.com',
            'note': 'my awesome note',
        }
        response = self.client.post(
            '/new/{}'.format(event_id), data=user_data, follow_redirects=True
        )
        assert response.status_code == 200
        assert user_data['name'] not in str(response.data)


class TestApi(BaseTest):

    def jsonget(self, path):
        response = self.client.get(path)
        return json.loads(response.data)

    def jsonpost(self, path, data):
        response = self.client.post(path, data=data)
        return json.loads(response.data)

    def test_rsvps_create(self):
        data = {'name': 'test-event', 'date': '2018-01-01'}
        with rsvp.app.test_request_context():
            event = rsvp.Event(**data)
            event.save()
            event_id = event.id
        assert self.jsonget("/api/rsvps/{}".format(event_id))['rsvps'] == []
        doc = self.jsonpost(
            "/api/rsvps/{}".format(event_id),
            '{"name": "test name", "email": "test@example.com"}',
        )
        assert doc['name'] == 'test name'
        assert doc['email'] == 'test@example.com'
        assert doc['_id'] is not None
        assert len(
            self.jsonget("/api/rsvps/{}".format(event_id))['rsvps']
        ) == 1

    def test_rsvps_delete(self):
        data = {'name': 'test-event', 'date': '2018-01-01'}
        with rsvp.app.test_request_context():
            event = rsvp.Event(**data)
            event.save()
            event_id = event.id
        assert self.jsonget("/api/rsvps/{}".format(event_id))['rsvps'] == []
        doc = self.jsonpost(
            "/api/rsvps/{}".format(event_id),
            '{"name": "test name", "email": "test@example.com"}',
        )
        assert len(
            self.jsonget("/api/rsvps/{}".format(event_id))['rsvps']
        ) == 1
        path = "/api/rsvps/{}/".format(event_id) + doc['_id']['$oid']
        self.client.delete(path)
        assert self.jsonget("/api/rsvps/{}".format(event_id))['rsvps'] == []
        response = self.client.get(path)
        assert response.status_code == 404
