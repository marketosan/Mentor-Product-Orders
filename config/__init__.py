"""Package init. Its one job is choosing a MySQL driver, when MySQL is in use.

Django's MySQL backend imports `MySQLdb`, which is the `mysqlclient` package:
a C extension needing a compiler and matching headers, and one whose prebuilt
wheels lag new Python releases -- there may well be none for 3.14 on Windows.
PyMySQL speaks the same API in pure Python, so it installs anywhere.

mysqlclient is preferred when present, since it is what Django tests against.
PyMySQL steps in only when it is missing. On SQLite neither is imported.
"""

try:
    import MySQLdb  # noqa: F401  (mysqlclient)
except ImportError:
    try:
        import pymysql
    except ImportError:
        # SQLite, or MySQL with no driver installed at all -- in which case
        # Django raises its own clear "Did you install mysqlclient?" error.
        pass
    else:
        # No version fiddling. PyMySQL already reports version_info as the
        # mysqlclient release it emulates -- (2, 2, 8) here, against Django's
        # floor of (2, 2, 1) -- and keeps its own number in pymysql.VERSION.
        # Overriding version_info to satisfy an older Django breaks this one.
        pymysql.install_as_MySQLdb()
