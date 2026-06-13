#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.9"
# dependencies = ["dropbox>=12"]
# ///
"""
Delete the RSVP app's MongoDB backup tarballs from Dropbox.

The backup job (`manage_db backup`) uploads files to the root of whatever the
token can see, named like:  heroku_cdbwn214-dump-2026-06-11-10-30-00.tar.gz

This script is DRY-RUN by default: it lists what matches and deletes nothing.
Pass --delete to actually remove them.

Setup:
    export DROPBOX_ACCESS_TOKEN="..."

Usage:
    uv run delete_dropbox_backups.py                 # dry run: list matches
    uv run delete_dropbox_backups.py --delete        # delete (asks to confirm)
    uv run delete_dropbox_backups.py --delete --yes  # delete without prompt
    uv run delete_dropbox_backups.py --pattern -dump- --path ""   # tweak match
"""

import argparse
import os
import sys

import dropbox
from dropbox.exceptions import ApiError, AuthError
from dropbox.files import DeleteArg, FileMetadata


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def list_all(dbx, path):
    """Yield FileMetadata entries under `path` (handles pagination)."""
    res = dbx.files_list_folder(path, recursive=False)
    while True:
        for entry in res.entries:
            if isinstance(entry, FileMetadata):
                yield entry
        if not res.has_more:
            break
        res = dbx.files_list_folder_continue(res.cursor)


def main():
    ap = argparse.ArgumentParser(
        description="Delete RSVP backup tarballs from Dropbox."
    )
    ap.add_argument(
        "--pattern",
        default="-dump-",
        help="substring a filename must contain to match (default: -dump-)",
    )
    ap.add_argument(
        "--suffix",
        default=".tar.gz",
        help="filename suffix that must match (default: .tar.gz)",
    )
    ap.add_argument(
        "--path",
        default="",
        help='folder to scan; "" = root the token can see (default: root)',
    )
    ap.add_argument(
        "--delete", action="store_true", help="actually delete (otherwise dry-run)"
    )
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    token = os.environ.get("DROPBOX_ACCESS_TOKEN")
    if not token:
        sys.exit("ERROR: set DROPBOX_ACCESS_TOKEN in your environment first.")

    dbx = dropbox.Dropbox(token)
    try:
        acct = dbx.users_get_current_account()
        print(f"Connected as: {acct.name.display_name} <{acct.email}>\n")
    except AuthError:
        sys.exit(
            "ERROR: token rejected. It may be expired or short-lived.\n"
            "Newer Dropbox tokens expire (~4h). Generate a fresh one in the\n"
            "Dropbox App Console (Generate access token), or use an app key/secret\n"
            "+ refresh token flow."
        )

    # find matching files
    matches = [
        e
        for e in list_all(dbx, args.path)
        if args.pattern in e.name and e.name.endswith(args.suffix)
    ]
    matches.sort(key=lambda e: e.name)

    if not matches:
        print(
            f"No files matching '*{args.pattern}*{args.suffix}' under "
            f"'{args.path or '/'}'. Nothing to do."
        )
        return

    total = sum(e.size for e in matches)
    print(f"Found {len(matches)} backup file(s), {human(total)} total:\n")
    for e in matches:
        when = (
            e.client_modified.strftime("%Y-%m-%d %H:%M") if e.client_modified else "?"
        )
        print(f"  {e.path_display:60s} {human(e.size):>9s}  {when}")
    print()

    if not args.delete:
        print("DRY RUN — nothing deleted. Re-run with --delete to remove these.")
        return

    if not args.yes:
        ans = input(f"Delete these {len(matches)} file(s)? This is permanent. [y/N] ")
        if ans.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return

    # batch delete in chunks of 1000 (API limit); poll each chunk until done
    import time

    entries = [DeleteArg(path=e.path_lower) for e in matches]
    print(f"\nDeleting {len(entries)} file(s)...")

    CHUNK = 1000
    all_results = []
    for i in range(0, len(entries), CHUNK):
        chunk = entries[i : i + CHUNK]
        print(f"  Batch {i // CHUNK + 1}: {len(chunk)} file(s)...")
        job = dbx.files_delete_batch(chunk)
        if job.is_complete():
            result = job.get_complete()
        else:
            token_id = job.get_async_job_id()
            while True:
                time.sleep(1)
                check = dbx.files_delete_batch_check(token_id)
                if check.is_complete():
                    result = check.get_complete()
                    break
                print("    ...still working")
        all_results.extend(result.entries)

    ok = sum(1 for r in all_results if r.is_success())
    failed = [r for r in all_results if not r.is_success()]
    print(f"Deleted {ok} file(s).")
    if failed:
        print(f"{len(failed)} failed:")
        for r in failed:
            print(f"  {r}")
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()
