# Deploying Mentor on cPanel hosting

For putting Mentor on a real domain that staff can reach from anywhere.

For the shop-machine-on-the-LAN setup instead, see [`DEPLOYMENT.md`](DEPLOYMENT.md).
Nothing from that guide is needed here — no XAMPP, no Apache config, no
`start_mentor.bat`, no Waitress. cPanel runs the app through **Phusion
Passenger**, which starts and stops Django for you.

---

## 0. Check this first, before anything else

**Two things decide whether this works at all.** Five minutes now saves an
afternoon.

### Does the host have "Setup Python App"?

Log into cPanel and look under **Software** for **Setup Python App** (some
hosts label it **Application Manager**).

Not there? Then the host does not support Python applications, and no amount of
uploading files will change that. Ask support whether Passenger/Python apps can
be enabled on your plan — on some it is a paid tier, on others it is simply not
offered, and then a small VPS is the alternative.

### Which Python versions does it offer?

Click **Create Application** and open the **Python version** dropdown. Write
down what you see, then close without creating anything.

| Versions offered | What it means |
|---|---|
| **3.12, 3.13 or 3.14** | Good. Continue to step 1. |
| **3.11 or lower** | **Stop.** Django 6 requires 3.12+. See below. |

If the highest is 3.11 or lower, Mentor cannot run as it stands. The options
are to ask the host whether a newer Python can be enabled, or to move the app
back to Django 5.x — which is real work, not a version bump: every feature was
built and tested against Django 6, so the whole test suite has to be run against
5.x and whatever differs fixed. Tell me the version and I will do it properly
rather than guess.

### While you are in there

Also note, though neither blocks you:

- The **domain or subdomain** you want — `mentor.yourdomain.com` is tidier than
  a subfolder, and easier to move later.
- Whether **SSH access** is available (cPanel → **Terminal**, or an SSH Access
  entry). It makes steps 4–6 far quicker. Everything below has a no-SSH path
  too.

---

## 1. Create the subdomain

cPanel → **Domains** → **Create A Domain** (or **Subdomains** on older
versions).

- Domain: `mentor.yourdomain.com`
- Document root: leave whatever it suggests, e.g. `mentor.yourdomain.com`

Wait for DNS to catch up before worrying that it does not load — usually
minutes, occasionally an hour.

## 2. Get the code onto the server

**With Git** (cPanel → **Git Version Control** → **Create**):

- Clone URL: `https://github.com/marketosan/Mentor-Product-Orders.git`
- Repository path: `mentor` — this puts it at `/home/<user>/mentor`

**Without Git**: download the repo ZIP from GitHub, upload through **File
Manager**, extract, and rename the folder to `mentor`.

> **Put the code outside `public_html`.** `/home/<user>/mentor` is right;
> `/home/<user>/public_html/mentor` is not. Anything under `public_html` is
> reachable over the web, and that includes `db.sqlite3` — the entire shop's
> data, downloadable by anyone who guesses the URL. Passenger serves the app
> from outside the web root on purpose.

## 3. Create the Python application

cPanel → **Setup Python App** → **Create Application**:

| Field | Value |
|---|---|
| Python version | the newest offered (3.12+) |
| Application root | `mentor` |
| Application URL | your subdomain |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

Click **Create**. cPanel builds a virtualenv and shows a command near the top
of the page that looks like:

```
source /home/<user>/virtualenv/mentor/3.13/bin/activate && cd /home/<user>/mentor
```

**Copy that line.** It is how you get a shell with the right Python, and every
command below assumes you have run it.

## 4. Install the dependencies

**With SSH** — cPanel → **Terminal**, then paste the activate line from step 3,
then:

```bash
pip install -r requirements.txt
```

**Without SSH** — back on the Setup Python App page, find **Configuration
files**, enter `requirements.txt`, and click **Run Pip Install**.

Nothing here needs a compiler, so this should not fail.

## 5. Configure it

Two ways. **Environment variables in cPanel are the better one** — they are not
files, so they cannot be served by accident or committed by mistake.

On the Setup Python App page, under **Environment variables**, add:

| Name | Value |
|---|---|
| `SECRET_KEY` | see below |
| `DEBUG` | `0` |
| `ALLOWED_HOSTS` | `mentor.yourdomain.com` |
| `CSRF_TRUSTED_ORIGINS` | `https://mentor.yourdomain.com` |
| `TIME_ZONE` | `Europe/Athens` |
| `DB_NAME` | `/home/<user>/mentor-data/mentor.sqlite3` |
| `HTTPS` | `0` for now — step 8 turns it on |

Generate the key with the venv active:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Then create the folder for the database, which deliberately sits **outside** the
code directory so a `git pull` can never touch it:

```bash
mkdir -p /home/<user>/mentor-data
```

Three that catch people:

- **`ALLOWED_HOSTS` takes no scheme. `CSRF_TRUSTED_ORIGINS` requires one**, and
  here it is `https://`, not `http://`. Get it wrong and pages load while every
  form fails.
- **`HTTPS=0` until step 8.** Turning it on before the certificate exists makes
  cookies secure-only and nobody can log in.
- If you use a `.env` file instead of cPanel variables, it must sit beside
  `manage.py` and **must not** be inside `public_html`.

## 6. Set up the database

With the venv active and in the app directory:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

No SSH? Setup Python App's **Execute python script** box runs these — enter
`manage.py` as the script and `migrate` as the arguments, and so on.

### Make yourself a shop admin

`createsuperuser` gets you into Django's `/admin/`, but **not** into Mentor's
own admin pages — those check the shop `role`, which starts as `employee`.
And `/users/`, the page that would fix it, is itself admin-only.

Break the loop once, from the shell:

```bash
python manage.py shell -c "from django.contrib.auth import get_user_model; U=get_user_model(); u=U.objects.get(username='admin'); u.role=U.Role.ADMIN; u.save(); print(u.username, u.role, u.is_shop_admin)"
```

It should print `admin admin True`. After that, any admin can promote others
from `/users/` and you never need this again.

## 7. Start it

Back on the Setup Python App page, click **Restart**.

Visit `http://mentor.yourdomain.com`. It should look right — styling included.
Static files are served by WhiteNoise inside the app, so there is no Apache
alias to configure and nothing to get wrong.

**Every time you change code or environment variables, click Restart.**
Passenger keeps the old process alive otherwise, and you will be very confused
about why your change did nothing. From SSH, `touch tmp/restart.txt` in the app
root does the same thing.

## 8. Turn on HTTPS

Now that it loads. cPanel → **SSL/TLS Status** → tick the subdomain → **Run
AutoSSL**. It issues a free Let's Encrypt certificate and renews it on its own.

Once `https://mentor.yourdomain.com` loads with a padlock, go back to
**Environment variables** and set:

```
HTTPS = 1
```

Then **Restart**. That switches on secure-only cookies, HSTS, and an automatic
redirect from `http://` to `https://`.

**In that order.** Setting `HTTPS=1` before the certificate works does not warn
— the browser simply refuses to send the session cookie over plain http, and
logging in silently fails.

This matters more than it did on the LAN: passwords now cross the open
internet. Do not leave this step for later.

---

## Updating

```bash
cd /home/<user>/mentor
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
touch tmp/restart.txt
```

With cPanel's Git Version Control you can also click **Update from Remote**,
but the `migrate`/`collectstatic`/restart steps still have to happen.

## Backups

The whole shop is in `/home/<user>/mentor-data/mentor.sqlite3`.

Your host's own cPanel backups probably cover it, but check — some plans back
up `public_html` and databases only, and this file is neither. Verify rather
than assume.

Take your own regardless:

```bash
python -c "import sqlite3,sys; s=sqlite3.connect('/home/<user>/mentor-data/mentor.sqlite3'); d=sqlite3.connect(sys.argv[1]); s.backup(d); d.close(); s.close()" ~/backups/mentor-$(date +%F).sqlite3
```

Use SQLite's backup API rather than `cp`: it takes a consistent snapshot even
mid-write, where a plain copy can catch a torn state. Worth a weekly cron job
in cPanel → **Cron Jobs**, and worth downloading a copy off the server
occasionally — a backup that only exists on the machine it is backing up is not
one.

## When something is wrong

| Symptom | Cause |
|---|---|
| **500, no detail** | By design with `DEBUG=0`. Read `logs/mentor.log` in the app root, or cPanel's **Errors**. |
| **`DisallowedHost`** | The domain is missing from `ALLOWED_HOSTS`. |
| **Forms fail, pages load** | `CSRF_TRUSTED_ORIGINS` missing, or still `http://` after enabling HTTPS. |
| **No styling** | `collectstatic` not run. |
| **Changes do nothing** | Not restarted. Click **Restart**, or `touch tmp/restart.txt`. |
| **Nobody can log in after step 8** | `HTTPS=1` set before the certificate was live. |
| **"passenger_wsgi.py not found"** | Application root or startup file wrong in step 3. |
| **Only "Home" in the menu** | The role step in step 6 did not run. |

## Worth knowing once it is public

None of these blocks the deployment, but the LAN assumptions no longer hold now
that anyone can reach the login page:

- **No rate limiting on login.** Nothing slows down repeated password guesses.
  Worth adding.
- **Sessions last 30 days**, chosen so shop staff stay logged in on their own
  phones. Reasonable there; long for a public site.
- **No password reset by email.** Resets go through an admin, which is fine
  while everyone shares a workplace.

Say the word and I will do any of them properly.
