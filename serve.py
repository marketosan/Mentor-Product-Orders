"""Run Mentor under Waitress, the production server on the shop's machine.

`manage.py runserver` is Django's development server: single-threaded, slow at
serving files, and explicitly not built to face real users. Waitress is a pure
Python WSGI server that runs on Windows, which gunicorn does not.

It listens on localhost only. Apache is what the network talks to, and it
forwards here -- so nothing reaches this port except from the same machine.

    python serve.py               # 127.0.0.1:8000
    python serve.py --port 8001
    python serve.py --host 0.0.0.0    # skip Apache, reachable on the LAN
"""

import argparse
import os

from waitress import serve

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    parser = argparse.ArgumentParser(description="Serve Mentor with Waitress.")
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Interface to bind. Leave as 127.0.0.1 when Apache is in front; "
             "0.0.0.0 exposes it to the network directly.",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--threads", type=int, default=8,
        help="Concurrent requests. A coffee shop needs very few; the default "
             "is already generous.",
    )
    args = parser.parse_args()

    # Imported after DJANGO_SETTINGS_MODULE is set, and after argument parsing
    # so that --help works without a valid .env.
    from django.core.wsgi import get_wsgi_application

    application = get_wsgi_application()

    print(f"Mentor is serving on http://{args.host}:{args.port}")
    print("Apache should forward to this address. Ctrl+C to stop.")
    serve(application, host=args.host, port=args.port, threads=args.threads)


if __name__ == "__main__":
    main()
