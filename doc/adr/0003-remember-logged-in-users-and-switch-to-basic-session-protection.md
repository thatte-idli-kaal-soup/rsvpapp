# 3. Remember logged in users and switch to basic session protection

Date: 2018-04-17

## Status

Accepted

## Context

Flask provides varying degrees of session protection - None, basic and strong.
We were previously using the strong setting, which means the user will have to
login, each time their session expires - they close the browser or their IP
address changes, etc. This practically means users will have to authenticate for
each event's RSVP, and it made enforcing logins painful.

## Decision

We will now use the basic session protection level, and turn on the "remember
me" cookie, making it easier for users to stay signed in.

## Consequences

It is easier for the users to stay signed in, and RSVP for everyday events as
logged in users, rather than anonymous ones. This will make it easier to add
permissions, and other features to the app.

But, it also makes the app a little less secure. So, the views which contain
sensitive data MUST use Flask's `fresh_login_required` decorator, instead of the
`login_required` decorator, to force the user to authenticate in this session.
