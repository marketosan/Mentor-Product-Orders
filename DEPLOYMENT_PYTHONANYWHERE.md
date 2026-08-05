# Deploying Mentor on PythonAnywhere (free tier)

Gets Mentor onto a public HTTPS address at no cost, reachable from any network.

Roughly 30 minutes. No server to maintain, no OS to patch, and the disk is
persistent — which is what lets the app keep using SQLite unchanged.

**What free costs you**, so it is not a surprise later:

- The address is `yourname.pythonanywhere.com`. Custom domains are paid only.
- **Every 3 months you must click a button** on the Web tab or the site stops
  serving. Put a recurring reminder in your calendar now, not later.
- One web app, a shared CPU quota, and no support guarantees.

None of that blocks a shop with a handful of staff. All of it goes away for a
few dollars a month if the shop comes to rely on it.

---

## 0. Check the Python version first

Django 6 needs **Python 3.12 or newer**. PythonAnywhere adds new versions on a
lag, so check before doing anything else.

Sign up for a free account at [pythonanywhere.com](https://www.pythonanywhere.com/),
then open the **Web** tab → **Add a new web app** → **Manual configuration**.
The next screen lists the Python versions available to you. Note the highest,
then leave the wizard without finishing.

| Highest offered | What to do |
|---|---|
| **3.12, 3.13 or 3.14** | Continue to step 1. |
| **3.10 or 3.11** | Stop — tell me. Mentor needs moving to Django 5.2 LTS. |
| **3.9 or lower** | Stop — tell me. Django 4.2 LTS, a bigger jump. |

Those fallbacks are exact, not guesses — Django 5.2 supports Python 3.10–3.13,
Django 4.2 supports 3.8–3.12. Either is real work rather than a version bump:
every feature here was built and tested against Django 6, so the whole suite has
to be run against the older one and whatever differs fixed. Tell me the number
and I will do it properly.

## 1. Open a Bash console

**Consoles** tab → **Bash**. Everything in steps 2–5 happens here.

## 2. Get the code

```bash
cd ~
git clone https://github.com/marketosan/Mentor-Product-Orders.git mentor
```

That puts it at `/home/yourname/mentor`. Everywhere below, replace `yourname`
with your actual PythonAnywhere username.

## 3. Create the virtualenv

Use the highest Python from step 0 — `3.13` here:

```bash
mkvirtualenv --python=/usr/bin/python3.13 mentor
pip install -r ~/mentor/requirements.txt
```

`mkvirtualenv` both creates and activates it; the prompt gains a `(mentor)`
prefix. In a new console later, `workon mentor` gets you back.

Note the path it created — `/home/yourname/.virtualenvs/mentor` — the Web tab
asks for it in step 6.

## 4. Configure it

PythonAnywhere has no environment-variable panel, so use a `.env` file. It is
gitignored, so it stays out of the repo.

```bash
cd ~/mentor
cp .env.example .env
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Copy the key it prints, then `nano .env` and set:

```ini
SECRET_KEY=<the key you just generated>
DEBUG=0
ALLOWED_HOSTS=yourname.pythonanywhere.com
CSRF_TRUSTED_ORIGINS=https://yourname.pythonanywhere.com
TIME_ZONE=Europe/Athens
DB_NAME=/home/yourname/mentor-data/mentor.sqlite3
HTTPS=1
```

Save with `Ctrl+O`, Enter, then `Ctrl+X`.

`HTTPS=1` is correct from the start here, unlike the other guides — free
PythonAnywhere accounts get a working HTTPS certificate on the
`.pythonanywhere.com` address automatically, so there is no window where the
setting is ahead of reality.

Then make the folder for the database. It sits **outside** the repo on purpose,
so a `git pull` can never touch it:

```bash
mkdir -p ~/mentor-data
```

## 5. Set up the database

```bash
cd ~/mentor
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

### Make yourself a shop admin

`createsuperuser` gets you into Django's `/admin/`, but **not** Mentor's own
admin pages — those check the shop `role`, which starts as `employee`. And
`/users/`, the page that would fix it, is admin-only itself.

Break the loop once:

```bash
python manage.py shell -c "from django.contrib.auth import get_user_model; U=get_user_model(); u=U.objects.get(username='admin'); u.role=U.Role.ADMIN; u.save(); print(u.username, u.role, u.is_shop_admin)"
```

Should print `admin admin True`. After this, any admin can promote others from
`/users/`.

## 6. Create the web app

**Web** tab → **Add a new web app**:

1. Domain: accept `yourname.pythonanywhere.com`
2. **Manual configuration** — *not* the Django option, which would scaffold a
   new empty project over the top
3. Python version: the same one as step 3

Then on the Web tab that appears, set:

| Field | Value |
|---|---|
| **Source code** | `/home/yourname/mentor` |
| **Working directory** | `/home/yourname/mentor` |
| **Virtualenv** | `/home/yourname/.virtualenvs/mentor` |

## 7. Point the WSGI file at Mentor

On the Web tab, click the **WSGI configuration file** link (something like
`/var/www/yourname_pythonanywhere_com_wsgi.py`). Delete everything in it and
put this in its place:

```python
import os
import sys

path = "/home/yourname/mentor"
if path not in sys.path:
    sys.path.insert(0, path)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

Save it.

This file does the same job as `passenger_wsgi.py` does on cPanel;
PythonAnywhere just keeps it outside your project. `passenger_wsgi.py` is
unused here and harmless.

## 8. Start it

Click the big green **Reload** button on the Web tab.

Visit `https://yourname.pythonanywhere.com`. It should load, styled, over
HTTPS.

Static files are served by WhiteNoise from inside the app, so there is no
static-files mapping to configure. You *can* add one on the Web tab
(URL `/static/`, directory `/home/yourname/mentor/staticfiles`) to have their
web server handle it instead — slightly faster, and it does not consume your
CPU quota. Optional.

**Every change needs a Reload.** Editing files or `.env` does nothing to the
running site until you press it.

---

## Shipping a change

Changes travel through GitHub. Never edit files on PythonAnywhere directly —
the next `git pull` will either overwrite them or refuse to merge.

**On your machine**, before pushing:

```bash
python manage.py test
```

All 372 should pass. Then commit and push.

**On PythonAnywhere**, in a Bash console:

```bash
workon mentor
cd ~/mentor
git pull
```

Then only what the change needs:

| If the change touched | Run |
|---|---|
| `requirements.txt` | `pip install -r requirements.txt` |
| anything in `*/migrations/` | `python manage.py migrate` |
| anything in `static/` | `python manage.py collectstatic --noinput` |
| **anything at all** | **Reload**, on the Web tab |

Running all three when unsure is harmless — each does nothing if there is
nothing to do.

**Back up before a migration.** A `git pull` can be undone; a migration often
cannot. Check whether one is coming:

```bash
python manage.py migrate --plan
```

"No planned migration operations" means nothing to undo. Anything else, take a
backup first.

## Backups

**Do this early.** The shop's entire history is one file, on a free account you
do not control.

```bash
mkdir -p ~/backups
python -c "import sqlite3,sys; s=sqlite3.connect('/home/yourname/mentor-data/mentor.sqlite3'); d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close(); s.close()" ~/backups/mentor-$(date +%F).sqlite3
```

SQLite's backup API rather than `cp`, because it takes a consistent snapshot
even mid-write.

Then **download it off the platform** — Files tab, navigate to `backups`, click
the download arrow. A backup that only exists on the machine it is backing up
is not a backup, and that goes double when the machine is a free account that
switches off if you forget to click a button.

Free accounts get one scheduled task a day (**Tasks** tab) — pointing it at the
command above automates the snapshot, though not the download.

## Keeping it alive

**Web tab → the "Run until 3 months from today" button.** Click it now, and set
a calendar reminder for ten weeks. Miss it and the site stops answering until
you log in and press it.

This is the single most likely reason the shop finds Mentor down one morning.

## When something is wrong

PythonAnywhere gives you two logs on the Web tab, and they answer most
questions:

- **Error log** — Python tracebacks
- **Server log** — startup problems, WSGI import failures

| Symptom | Cause |
|---|---|
| **"Something went wrong :-("** | An unhandled error. Read the Error log. |
| **`DisallowedHost`** | `ALLOWED_HOSTS` does not have your `.pythonanywhere.com` address. |
| **Forms fail, pages load** | `CSRF_TRUSTED_ORIGINS` missing, or `http://` instead of `https://`. |
| **No styling** | `collectstatic` not run. |
| **Changes do nothing** | Not reloaded. |
| **Redirect loop** | `HTTPS=1` but the proxy header is not arriving. Set `HTTPS=0`, Reload, and tell me. |
| **`ModuleNotFoundError: config`** | The path in the WSGI file is wrong. |
| **Only "Home" in the menu** | The shop-admin step in step 5 did not run. |
| **Site simply stopped** | The 3-month renewal lapsed. |

## Worth doing once it is live

Anyone can now reach the login page, which was not true on the shop LAN:

- **No rate limiting on login** — nothing slows repeated password guesses.
- **Sessions last 30 days**, chosen for staff phones. Long for a public site.
- **No password reset by email** — resets go through an admin.

Say the word and I will do any of them properly.
