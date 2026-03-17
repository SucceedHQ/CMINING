# This is the WSGI file PythonAnywhere needs.
# On PythonAnywhere: Web tab → WSGI configuration file → paste this

import sys
import os

# Add your project folder to the path
project_home = '/home/SucceedHQ/CMining-Monorepo/backend'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Load .env file if present
from dotenv import load_dotenv
load_dotenv(os.path.join(project_home, '.env'))

# Import the Flask app
from app import app as application  # noqa
