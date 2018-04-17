# 2. Don't save Google tokens in the DB

Date: 2018-04-17

## Status

Accepted

## Context

Previously, we were saving the Google tokens for users in the DB. We don't
really do anything with the Google API and are using it only to authenticate the
user. Storing the tokens is just an additional security risk to mitigate, even
though the tokens expire in an hour.

## Decision

We will not store user tokens in the DB

## Consequences

If we wish to integrate further with Google's API, we might need the tokens, but
currently this decision will not have an impact on any of the existing code or
features. The mongo document for user will be smaller in size.
