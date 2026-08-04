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
                     MariaDB  :3306  (XAMPP)
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

During install, tick **"Add python.exe to PATH"**. Then check:

```bat
python --version
```

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

`requirements.txt` uses **PyMySQL**, a pure-Python MySQL driver, precisely so
this step cannot fail for want of a C compiler. If you would rather use
`mysqlclient` (what Django tests against), install it as well and it takes
precedence automatically — see `config/__init__.py`.

## 4. Create the database

Start **Apache** and **MySQL** from the XAMPP control panel, then open
<http://localhost/phpmyadmin>.

1. **Databases** → create `mentor`, collation **`utf8mb4_unicode_ci`**.
   The collation matters: the app stores Greek product names.
2. **User accounts** → **Add user account**
   - Username `mentor`, hostname `localhost`, and a password you generate
   - **Do not** tick "Create database with same name" — it already exists
   - Grant **all privileges on `mentor`** only, not globally

Using the `root` account with a blank password works and is what XAMPP ships
with. Don't. Anything else on that machine can then read and rewrite the shop's
order history.

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

DB_ENGINE=mysql
DB_NAME=mentor
DB_USER=mentor
DB_PASSWORD=<the password from step 4>
DB_HOST=127.0.0.1
DB_PORT=3306

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

## 8. Start the app

Double-click **`start_mentor.bat`**. It checks the venv and `.env` exist and
that migrations are applied, then starts Waitress. Leave the window open —
closing it stops the app.

Visit `http://<this-pc-ip>/`. Styled this time.

### Making it survive a reboot

The `.bat` needs someone to double-click it. To have Windows start it
automatically, install [NSSM](https://nssm.cc/):

```bat
nssm install Mentor "C:\mentor\.venv\Scripts\python.exe" "C:\mentor\serve.py"
nssm set Mentor AppDirectory C:\mentor
nssm set Mentor Start SERVICE_AUTO_START
nssm start Mentor
```

Also set XAMPP's Apache and MySQL to start as services, from the XAMPP panel's
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

The whole shop is in the database. Back it up somewhere that is not this
machine:

```bat
C:\xampp\mysql\bin\mysqldump -u mentor -p mentor > mentor-backup.sql
```

Worth a scheduled task, weekly, writing to a dated filename on a drive or share
that is not this computer. A backup sitting on the machine that dies is not a
backup.

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
- **Migrations have only been run against SQLite.** They should apply cleanly
  to MariaDB, and step 6 is where you find out. Nothing else in the app depends
  on which database is underneath.
- **Existing `db.sqlite3` data does not move across.** Step 6 starts empty. To
  carry data over: `manage.py dumpdata --natural-foreign --exclude=contenttypes
  --exclude=auth.permission > data.json` on the old database, then `loaddata`
  after migrating the new one.
