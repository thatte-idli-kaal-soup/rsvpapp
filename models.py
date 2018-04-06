import json

from pymodm import fields, MongoModel


class User(MongoModel):
    email = fields.EmailField(primary_key=True)
    name = fields.CharField()
    active = fields.CharField()
    tokens = fields.CharField()

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return self.email

    def toJSON(self):
        return json.dumps(
            self, default=self.__dict__, sort_keys=True, indent=4
        )

    def set_tokens(self, tokens):
        self.tokens = tokens
