# Deploying Mentor on the shop's Windows machine (XAMPP)

Everything below happens on the machine that will run the app. Roughly 45
minutes the first time.

## How the pieces fit

XAMPP's Apache faces the network. It serves the CSS and JS itself, and hands
everything else to Django, which runs as its own process under Waitress:

```
staff phones / tills
        │
        ▼
  Apache  :80          (XAMPP)
   ├── /static/  ──►  staticfiles\   served straight off disk
   └── /         ──►  127.0.0.1:8000
                            │
                            ▼
                     Waitress  ──►  Mentor
                            │
                            ▼
                     db.sqlite3   one file on disk
```

Django does **not** run inside Apache. That would need `mod_wsgi`, a compiled
extension that must match your exact Apache build and Python version, and it
frequently has no prebuilt wheel for a new Python. The proxy above needs
nothing compiled.

---

## 1. Install Python

Get it from [python.org](https://www.python.org/downloads/windows/) — **not**
the Microsoft Store version, which sandboxes file access in ways that trip up
service managers.

**Version:** 3.12, 3.13 or 3.14 all work. 3.13 is the safer pick for a machine
you will not babysit: if you ever add a package with compiled parts, prebuilt
wheels appear for the older version first.

**Where:** in the installer, tick both

- ☑ **Add python.exe to PATH**
- ☑ **Install for all users**

"Install for all users" puts it in `C:\Program Files\Python313` instead of
`C:\Users\<you>\AppData\Local\...`. That matters at step 8: a Windows service
runs as a different account, which cannot see another user's `AppData` folder.
Installing per-user works fine until you try to make Mentor start on boot, and
then fails with a confusing "file not found".

If you would rather avoid the space in "Program Files", choose **Customize
installation** and set the path to `C:\Python313`. Either is fine.

Check it:

```bat
python --version
where python
```

Both should answer, and the path should match where you installed it. If
`where python` prints something under `WindowsApps`, the Store version is
shadowing yours — remove it from **Settings → Apps → App execution aliases**.

The project's own virtual environment (step 3) lives in `C:\Users\marketos\Desktop\mentor.venv` and
is created from this Python. It records the path, so moving or uninstalling
Python later breaks the venv — deleting `.venv` and redoing step 3 fixes it.

## 2. Get the code onto the machine

```bat
cd C:\
git clone https://github.com/marketosan/Mentor-Product-Orders.git mentor
cd C:\mentor
```

No Git on the machine? Download the ZIP from GitHub and extract to `C:\mentor`.
Git makes updates one command instead of a re-download, so it is worth having.

## 3. Create the environment

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Nothing here needs a C compiler, so this step cannot fail for want of one.

## 4. The database

**Nothing to do.** The app uses SQLite: a single file, `db.sqlite3`, created
beside `manage.py` by the migrate step below. No server, no credentials, no
database server involved.

That is the deployment choice, not a development shortcut. The usual "don't use
SQLite in production" advice is about several web servers sharing one database
over a network, and about heavy concurrent writes. Neither happens here: one
machine runs everything off one disk, and a coffee shop's ordering tool is
mostly reads with an occasional write. Adding a database server would buy
nothing and cost a process that has to stay running.

## 5. Write the .env file

Copy `.env.example` to `.env` in `C:\mentor`, then fill it in. Generate the key
with:

```bat
.venv\Scripts\python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

A working `.env` for a LAN deployment at `192.168.1.50`:

```ini
SECRET_KEY=<paste the generated key>
DEBUG=0
ALLOWED_HOSTS=192.168.1.50,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://192.168.1.50,http://localhost
TIME_ZONE=Europe/Athens

HTTPS=0
```

Two that catch everybody:

- **`ALLOWED_HOSTS` has no scheme; `CSRF_TRUSTED_ORIGINS` must have one.**
  Get the second wrong and pages load fine but every form fails with a CSRF
  error.
- **Leave `HTTPS=0` until Apache actually serves HTTPS.** Setting it early does
  not warn — it makes cookies secure-only, and nobody can log in over `http://`.

`.env` is gitignored. It never leaves this machine.

## 6. Set up the database contents

```bat
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py createsuperuser
.venv\Scripts\python manage.py collectstatic --noinput
```

`createsuperuser` makes a Django admin account. It is **not** automatically a
shop admin — after logging in, open `/users/` and set its role to Admin, or
give it `role=admin` in `/admin/`.

Skip `collectstatic` and the app loads with no styling at all: with `DEBUG=0`
Django serves no static files, by design.

Check it before involving Apache:

```bat
.venv\Scripts\python manage.py check --deploy
.venv\Scripts\python serve.py --host 0.0.0.0
```

Visit `http://<this-pc-ip>:8000`. It will look unstyled — Apache is not serving
`/static/` yet. Stop it with Ctrl+C.

## 7. Point Apache at it

> **Running on this machine only, to try it out?** Use the port-8080 vhost in
> [Localhost only](#localhost-only) below instead of the one here, and skip
> steps 9 and the static-IP note. Everything else is the same.

Open `C:\xampp\apache\conf\httpd.conf` and make sure these three are **not**
commented out:

```apache
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_http_module modules/mod_proxy_http.so
LoadModule headers_module modules/mod_headers.so
```

Then add to `C:\xampp\apache\conf\extra\httpd-vhosts.conf`:

```apache
<VirtualHost *:80>
    ServerName mentor.local

    # Apache serves the CSS and JS. Faster than Python, and it means Django
    # never sees those requests at all.
    Alias /static/ "C:/mentor/staticfiles/"
    <Directory "C:/mentor/staticfiles">
        Require all granted
        Options -Indexes
    </Directory>

    # Everything else goes to Waitress. /static/ is excluded above, so it is
    # excluded here too.
    ProxyPreserveHost On
    ProxyPass        /static/ !
    ProxyPass        / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    # Lets Django know the original scheme once you move to HTTPS.
    RequestHeader set X-Forwarded-Proto "http"

    ErrorLog  "logs/mentor-error.log"
    CustomLog "logs/mentor-access.log" combined
</VirtualHost>
```

Forward slashes in Windows paths inside Apache config — backslashes will not
work.

Restart Apache from the XAMPP panel. If it refuses to start, the panel's
**Logs → Apache (error.log)** button says why; a typo in this file is the usual
cause.

### Localhost only

Careful here: **defining a vhost makes it the default for anything that does
not match another one**, and `ProxyPass /` then swallows the whole of
`htdocs` — phpMyAdmin included. You would have Mentor and no way into the
database.

The clean way to avoid that is to leave port 80 alone and give Mentor its own.
In `httpd.conf`, next to the existing `Listen 80`:

```apache
Listen 8080
```

Then in `httpd-vhosts.conf`, instead of the vhost above:

```apache
<VirtualHost *:8080>
    ServerName localhost

    Alias /static/ "C:/mentor/staticfiles/"
    <Directory "C:/mentor/staticfiles">
        Require all granted
        Options -Indexes
    </Directory>

    ProxyPreserveHost On
    ProxyPass        /static/ !
    ProxyPass        / http://127.0.0.1:8000/
    ProxyPassReverse / http://127.0.0.1:8000/

    RequestHeader set X-Forwarded-Proto "http"

    ErrorLog  "logs/mentor-error.log"
    CustomLog "logs/mentor-access.log" combined
</VirtualHost>
```

Now:

| | |
|---|---|
| <http://localhost:8080/> | Mentor |
| <http://localhost/phpmyadmin> | still works, untouched |

`.env` for this case:

```ini
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
```

The **port belongs in `CSRF_TRUSTED_ORIGINS`** and must not appear in
`ALLOWED_HOSTS`. Django compares origins including the port, and hostnames
without it.

Skipping Apache entirely and just running `serve.py` does work, but the page
arrives with no styling: with `DEBUG=0` Django serves no static files, and
there is then nothing serving `/static/`.

## 8. Start the app

Double-click **`start_mentor.bat`**. It checks the venv and `.env` exist and
that migrations are applied, then starts Waitress. Leave the window open —
closing it stops the app.

Visit `http://<this-pc-ip>/`. Styled this time.

### Making it survive a reboot

The `.bat` needs someone to double-click it. To have Windows start it
automatically, install [NSSM](https://nssm.cc/):

```bat
nssm install Mentor "C:\Users\marketos\Desktop\mentor.venv\Scripts\python.exe" "C:\Users\marketos\Desktop\mentorserve.py"
nssm set Mentor AppDirectory C:\mentor
nssm set Mentor Start SERVICE_AUTO_START
nssm start Mentor
```

Also set XAMPP's Apache to start as a service, from the XAMPP panel's
config checkboxes. Otherwise a power cut means someone has to log in and start
three things by hand.

## 9. Let the other devices reach it

Windows Firewall blocks port 80 from other machines by default:

```
Windows Defender Firewall → Advanced settings → Inbound Rules → New Rule
  Port → TCP → 80 → Allow → Private network only
```

**Private network only.** If this machine is ever on public Wi-Fi, that setting
is the difference between the shop's staff and everyone in the café.

Give the machine a static IP, or a DHCP reservation on the router. If its
address changes, every phone's bookmark breaks.

---

## Backups

The whole shop is in one file, `C:\Users\marketos\Desktop\mentordb.sqlite3`. Backing up is copying
it — this is the part of SQLite that is genuinely nicer than a database server.

Use SQLite's own backup command rather than plain `copy`. It takes a consistent
snapshot even while the app is running and mid-write; a raw file copy of a
database being written to can capture a torn half-state.

```bat
cd C:\mentor
.venv\Scripts\python -c "import sqlite3,sys; s=sqlite3.connect('db.sqlite3'); d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close(); s.close()" \\nas\backups\mentor-%date:~-4%%date:~3,2%%date:~0,2%.sqlite3
```

Worth a weekly scheduled task writing to a dated filename on a drive or share
that is **not this computer**. A backup sitting on the machine that dies is not
a backup.

Restoring is copying the file back over `db.sqlite3` with the app stopped.

## Updating

```bat
cd C:\mentor
git pull
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py collectstatic --noinput
```

Then restart the Waitress window (or `nssm restart Mentor`). Apache does not
need restarting unless the vhost changed.

## When something is wrong

| Symptom | Cause |
|---|---|
| **500, no detail** | By design with `DEBUG=0`. The traceback is in `logs\mentor.log`. |
| **`DisallowedHost`** | The address used is missing from `ALLOWED_HOSTS`. |
| **Forms fail, pages load** | `CSRF_TRUSTED_ORIGINS` missing the scheme, or the address. |
| **No styling** | `collectstatic` not run, or the Apache `Alias` path is wrong. |
| **502 / "Service Unavailable"** | Waitress is not running. Apache is up, the app is not. |
| **Nobody can log in after enabling HTTPS** | `HTTPS=1` while Apache still serves plain `http`. |
| **Works on the machine, not on phones** | Firewall rule, or the machine's IP changed. |

## Not done yet

- **HTTPS.** Everything runs over plain `http` on the LAN, so passwords cross
  the network in the clear. Acceptable on a private shop network; not if this
  is ever reachable from outside. Set `HTTPS=1` in the same change that puts a
  certificate on Apache, never before.
- **The shop starts with an empty database.** Step 6 creates it from nothing.
  To carry data over from another machine, run this on the old one:

  ```bat
  manage.py dumpdata --natural-foreign --exclude=contenttypes --exclude=auth.permission > data.json
  ```

  then `manage.py loaddata data.json` on the new one after migrating. Passwords
  survive; they are hashed in the dump.
