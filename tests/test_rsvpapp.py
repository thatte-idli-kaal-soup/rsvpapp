import rsvp
import mongomock
import unittest
import json
from bson.objectid import ObjectId


class BaseTest:

    def setup_method(self, method):
        rsvp.client = mongomock.MongoClient()
        rsvp.db = rsvp.client.mock_db_function
        self.client = rsvp.app.test_client()


class TestRSVP(BaseTest):

    def test_dict(self):
        doc = rsvp.RSVP("test name", "test@example.com", "1", "1")
        with rsvp.app.test_request_context():
            assert doc.dict() == {
                "_id": "1",
                "name": "test name",
                "email": "test@example.com",
                "links": {"self": "http://localhost/api/rsvps/1/1"},
            }

    def test_new(self):
        RSVP = rsvp.RSVP
        event_id = "1"
        doc = RSVP.new("test name", "test@example.com", event_id)
        assert doc.name == "test name"
        assert doc.email == "test@example.com"
        assert doc._id is not None
        assert RSVP.find_one(event_id, doc._id) is not None
        assert len(RSVP.find_all(event_id)) == 1


class TestRSVPApp(BaseTest):

    def test_create_event(self):
        event_data = {'name': 'test_event', 'date': '2018-01-01'}
        response = self.client.post(
            '/event', data=event_data, follow_redirects=True
        )
        assert response.status_code == 200

    def test_rsvp(self):
        event_data = {'name': 'test_event', 'date': '2018-01-01'}
        response = self.client.post(
            '/event', data=event_data, follow_redirects=True
        )
        response = self.client.get('/api/events', follow_redirects=True)
        events = json.loads(response.data)
        event_id = events[0]['_id']
        user_data = {
            'name': 'test_name', 'email': 'test_email@test_domain.com'
        }
        response = self.client.post(
            '/new/{}'.format(event_id), data=user_data, follow_redirects=True
        )
        assert response.status_code == 200


class TestApi(BaseTest):

    def jsonget(self, path):
        response = self.client.get(path)
        return json.loads(response.data)

    def jsonpost(self, path, data):
        response = self.client.post(path, data=data)
        return json.loads(response.data)

    def test_rsvps_empty(self):
        assert self.jsonget("/api/rsvps/1") == []

    def test_rsvps_create(self):
        assert self.jsonget("/api/rsvps/1") == []
        doc = self.jsonpost(
            "/api/rsvps/1",
            '{"name": "test name", "email": "test@example.com"}',
        )
        assert doc['name'] == 'test name'
        assert doc['email'] == 'test@example.com'
        assert doc['_id'] is not None
        assert len(self.jsonget("/api/rsvps/1")) == 1

    def test_rsvps_delete(self):
        assert self.jsonget("/api/rsvps/1") == []
        doc = self.jsonpost(
            "/api/rsvps/1",
            '{"name": "test name", "email": "test@example.com"}',
        )
        assert len(self.jsonget("/api/rsvps/1")) == 1
        path = "/api/rsvps/1/" + doc['_id']
        self.client.delete(path)
        assert self.jsonget("/api/rsvps/1") == []
        response = self.client.get(path)
        assert response.status_code == 404
