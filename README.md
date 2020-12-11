# rsvpapp

RSVP app for TIKS

## Developer help

### Installation & Running the app (without Docker/Dokku)

1. Setup MongoDB on your machine.

   If you are a developer from `thatteidlikaalsoup`, and don't want to spend the
   time and effort to setup MongoDB, ask @punchagan for access to a Test DB,
   against which you can develop.

1. Setup a virtualenv and activate it

```sh
virtualenv -p python3 /path/to/venv
source /path/to/venv/bin/activate
```

2. Install the requirements

```sh
pip install -r requirements.txt
```

3. Setup environment variables

```sh
export LOGO=https://thatteidlikaalsoup.team/icons/icon-144x144.png
export TEXT1="Thatte Idli Kaal Soup"
export TEXT2="Practice RSVP"
export COMPANY="Thatte Idli Kaal Soup"
export DEBUG=1
export SETTINGS="settings/conf.py"
# Google Auth
export GOOGLE_CLIENT_ID="yyy"
export GOOGLE_CLIENT_SECRET="xxx"
# If not using https (use only for local development!)
export OAUTHLIB_INSECURE_TRANSPORT=1
```

4. Run the app

```sh
python rsvp.py
```

### Authentication

The app uses Google OAuth for authentication. But, to allow developers to work
on the app without having the whole Google auth stuff setup, a `dev_login`
method is available for developers.

You need to set an environment variable, `NO_GOOGLE_AUTH=1`.
