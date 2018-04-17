# 4. Backup nightly to Dropbox

Date: 2018-04-18

## Status

Accepted

## Context

mLab - the mongodb provider for Heroku doesn't provide free backups for the DB.
This leaves us vulnerable. We have decided to write our own script to create
backups. We need to be able to upload the backup tarballs to somewhere on the
web, from the Heroku cron dynos. Google Drive seemed like the natural choice,
but it doesn't allow OAuth1.0 access.

## Decision

We have decided to upload to Dropbox, instead of trying to upload to Google
Drive.

## Consequences

We have to configure a Dropbox app and setup it's ACCESS_TOKEN as an envvar to
be able to run backups. This makes us dependent on setting up apps on two
different platforms - Dropbox and Google.

Also, to be able to run `mongodump` on Heroku, we have to use a buildpack that
makes this command available to us. Just to be able to run backups on Heroku, we
have had to add another buildpack. This complicates the app setup for someone
wanting to try to deploy this app. We could consider running the backup
elsewhere (maybe on Travis), but that is going to make it two different
platforms to manage for a user.
