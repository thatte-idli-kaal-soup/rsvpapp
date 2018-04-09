from requests_oauthlib import OAuth2Session


class Auth:
    """Google Project Credentials"""
    CLIENT_ID = (
        '272522227133-njffi4vemudjsi3b2jq205lnb22mmn1p.apps.googleusercontent.com'
    )
    CLIENT_SECRET = '74fTVh2xPlvTKilT1V-LbUOL'
    AUTH_URI = 'https://accounts.google.com/o/oauth2/auth'
    TOKEN_URI = 'https://accounts.google.com/o/oauth2/token'
    USER_INFO = 'https://www.googleapis.com/userinfo/v2/me'
    SCOPE = ['profile', 'email']


def get_google_auth(state=None, token=None, redirect_uri=None):
    if token:
        return OAuth2Session(Auth.CLIENT_ID, token=token)

    if state:
        return OAuth2Session(
            Auth.CLIENT_ID, state=state, redirect_uri=redirect_uri
        )

    oauth = OAuth2Session(
        Auth.CLIENT_ID, redirect_uri=redirect_uri, scope=Auth.SCOPE
    )
    return oauth
