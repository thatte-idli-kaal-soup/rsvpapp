import datetime
import json
from unittest.mock import patch

from rsvp import app, models, views  # noqa


class BaseTest:
    def setup_method(self, method):
        self.client = app.test_client()
        with app.test_request_context():
            connection = models.db.connection
            connection.drop_database("rsvpdata")
            self.user = models.User(email="foo@example.com", name="Test User")
            self.user.save()


class TestRSVPApp(BaseTest):
    def test_create_event(self):
        event_data = {
            "event-name": "test_event",
            "date": "2018-01-01",
            "time": "06:00",
            "event-description": "Awesome event",
        }
        with patch("rsvp.views.current_user", new=self.user):
            response = self.client.post(
                "/event", data=event_data, follow_redirects=True
            )
        assert response.status_code == 200


class TestApi(BaseTest):
    def jsonget(self, path):
        response = self.client.get(path)
        return json.loads(response.data)

    def jsonpost(self, path, data):
        response = self.client.post(path, data=data)
        return json.loads(response.data)

    def test_rsvps_create(self):
        data = {"name": "test-event", "date": "2018-01-01"}
        with app.test_request_context():
            event = models.Event(**data)
            event.save()
            event_id = event.id
        assert self.jsonget("/api/rsvps/{}".format(event_id))["rsvps"] == []
        doc = self.jsonpost(
            "/api/rsvps/{}".format(event_id),
            '{{"user": "{}", "rsvp_by": "test@example.com"}}'.format(
                self.user.email
            ),
        )
        assert doc["user"] == self.user.email
        assert doc["rsvp_by"] == "test@example.com"
        assert doc["_id"] is not None
        assert (
            len(self.jsonget("/api/rsvps/{}".format(event_id))["rsvps"]) == 1
        )

    def test_rsvps_delete(self):
        data = {"name": "test-event", "date": "2018-01-01"}
        with app.test_request_context():
            event = models.Event(**data)
            event.save()
            event_id = event.id
        assert self.jsonget("/api/rsvps/{}".format(event_id))["rsvps"] == []
        doc = self.jsonpost(
            "/api/rsvps/{}".format(event_id),
            '{{"user": "{}"}}'.format(self.user.email),
        )
        assert (
            len(self.jsonget("/api/rsvps/{}".format(event_id))["rsvps"]) == 1
        )
        path = "/api/rsvps/{}/".format(event_id) + doc["_id"]["$oid"]
        self.client.delete(path)
        rsvps = self.jsonget("/api/rsvps/{}".format(event_id))["rsvps"]
        assert len(rsvps) == 1
        assert rsvps[0]["cancelled"]
        response = self.client.get(path)
        assert response.status_code == 200
