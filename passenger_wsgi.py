"""Entry point for cPanel's "Setup Python App", which runs Phusion Passenger.

Passenger imports this file and looks for a module-level `application`. That is
the whole contract -- the real WSGI app is still `config/wsgi.py`, and this only
exists because Passenger insists on finding it here, in the application root.

Nothing starts a server: Passenger owns the process, spawning and reaping
workers as requests arrive. `serve.py` (Waitress) is for a machine you run
yourself, and is unused here.
"""

import os
import sys

# Passenger's working directory is not reliably the application root, so make
# the import of `config` work regardless of where it was launched from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402  (path first)

application = get_wsgi_application()
