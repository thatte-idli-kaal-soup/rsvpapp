import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conf import *

MONGODB_SETTINGS = {
    'host': os.environ.get(
        'MONGODB_URI', 'mongomock://localhost:27017/rsvpdata'
    )
}
