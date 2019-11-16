#!/usr/bin/env python
from rsvp import app

if __name__ == '__main__':
    app.jinja_env.cache = None
    app.run(host='0.0.0.0')
