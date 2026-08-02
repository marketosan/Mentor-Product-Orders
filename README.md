# Mentor — Coffee Shop Procurement App

Internal tool for tracking products that need reordering. Employees flag items
running low; an admin sees them grouped by seller, places the orders outside
the app, then marks them completed.

Full spec: [`specs/mentor-app-spec.md`](specs/mentor-app-spec.md)

Django 6 · HTMX · Tailwind (CDN) · SQLite

## Running it

```bash
cd ~/projects/Mentor-Product-Orders
.venv/bin/python manage.py runserver
```

Then open <http://localhost:8000>. **Press `Ctrl+C` to stop it.**

Every request is logged in that terminal as it happens, along with the full
traceback of any error. Leave the window visible while clicking around — the
server auto-reloads whenever a `.py` file changes, so there is no need to
restart after a code edit. Template and CSS edits just need a browser refresh.

If you would rather not type `.venv/bin/python` each time:

```bash
source .venv/bin/activate     # now plain `python manage.py ...` works
deactivate                    # when you are done
```

### Is something already running?

```bash
ss -ltnp | grep :8000                 # anything listening on the port?
pgrep -af "[m]anage.py runserver"     # any server process?
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/
```

No output from the first two means nothing is running; `000` from the third
means nothing answered.

The brackets in `[m]anage` matter. Without them `pgrep` matches its own
command line and reports a server that is not there.

### Port already in use

`Error: That port is already in use.` means a server is still running
somewhere — either in another terminal, or left behind by a crashed one:

```bash
pkill -f "manage.py runserver"     # stop whatever is holding it
.venv/bin/python manage.py runserver 8001   # or just use another port
```

## Logging in

`manage.py seed_demo` creates demo sellers, products and open items, plus two
accounts. It is safe to re-run — it never duplicates anything.

| user | password | role |
|---|---|---|
| `maria` | `mentor123` | employee |
| `admin` | `admin` | admin, and the Django admin at `/admin` |

## Everyday commands

```bash
.venv/bin/python manage.py runserver      # start (Ctrl+C to stop)
.venv/bin/python manage.py seed_demo      # (re)create demo data
.venv/bin/python manage.py makemigrations # after changing models.py
.venv/bin/python manage.py migrate        # apply model changes to the database
.venv/bin/python manage.py check          # config sanity check, no server needed
.venv/bin/python manage.py createsuperuser
```

## Starting over

The database is a single file, so resetting is just deleting it:

```bash
rm db.sqlite3
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo
```

## Reading the logs

Requests appear as they happen:

```
[02/Aug/2026 15:51:36] "GET /products/search/?q=mil HTTP/1.1" 200 631
[02/Aug/2026 15:51:37] "POST /items/add/ HTTP/1.1" 422 10722
```

`200` succeeded · `302` redirected · `422` a form was rejected as invalid ·
`404` no such URL · `500` a crash, with the traceback printed underneath.

Server logs only cover what reaches Django. A blank page, wrong styling or a
dead button is usually JavaScript, which only the browser sees — open the
console with `F12` for those.
