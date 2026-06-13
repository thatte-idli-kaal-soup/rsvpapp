#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.9"
# dependencies = ["pymongo>=4"]
# ///
"""
List posts, and export selected ones to Hugo content files (markdown + TOML header).

Two modes:
  --list                 print every post (id, date, flags, authors, title)
  <ids...>               export the given post IDs as Hugo .md files

Usage:
    uv run posts_to_hugo.py --list                       # browse what's there
    uv run posts_to_hugo.py --list --public-only         # only public, non-draft
    uv run posts_to_hugo.py 665f1a..  665f2b..           # export these IDs
    uv run posts_to_hugo.py --out content/posts 665f1a..
    uv run posts_to_hugo.py --by-id 665f1a..             # name files by id, not slug
    uv run posts_to_hugo.py --ids-file ids.txt           # ids from a file (one per line)
    uv run posts_to_hugo.py --uri mongodb://localhost:27017 --db heroku_cdbwn214 --list

IDs can be bare 24-char hex or wrapped like ObjectId("...") — both are accepted.
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

from bson import ObjectId
from bson.dbref import DBRef
from pymongo import MongoClient


def clean_id(raw):
    """Accept '665f..', 'ObjectId(\"665f..\")', quotes, whitespace."""
    m = re.search(r"[0-9a-fA-F]{24}", raw)
    if not m:
        raise ValueError(f"not a valid ObjectId: {raw!r}")
    return ObjectId(m.group(0))


def slugify(s):
    s = (s or "untitled").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80] or "untitled"


def toml_str(s):
    """Escape a Python string for a TOML basic string (double-quoted)."""
    s = str(s)
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{s}"'


def toml_str_array(items):
    return "[" + ", ".join(toml_str(x) for x in items) + "]"


def author_key(a):
    if a is None:
        return None
    if isinstance(a, DBRef):
        return a.id
    if isinstance(a, dict):
        return a.get("$id") or a.get("oid") or str(a)
    return str(a)


def to_rfc3339(value):
    """TOML native datetime (unquoted). Returns None if not a datetime."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return value.strftime("%Y-%m-%dT%H:%M:%SZ")
        return value.isoformat()
    return None


def build_user_map(db):
    users = {}
    for u in db.user.find({}, {"name": 1, "nick": 1}):
        users[u["_id"]] = u.get("nick") or u.get("name") or u["_id"]
    return users


def resolve_authors(post, users):
    out = [users.get(author_key(a), author_key(a)) for a in (post.get("authors") or [])]
    return [a for a in out if a]


def list_posts(db, users, public_only=False):
    q = {"draft": {"$ne": True}, "public": True} if public_only else {}
    n = 0
    for p in db.post.find(
        q, {"title": 1, "authors": 1, "draft": 1, "public": 1, "created_at": 1}
    ).sort("created_at", -1):
        created = p.get("created_at")
        date = (
            created.strftime("%Y-%m-%d")
            if isinstance(created, dt.datetime)
            else "undated"
        )
        flags = (
            ",".join(
                f
                for f in [
                    "draft" if p.get("draft") else None,
                    "public" if p.get("public") else None,
                ]
                if f
            )
            or "-"
        )
        authors = ", ".join(resolve_authors(p, users)) or "(none)"
        print(
            f"{p['_id']}\t{date}\t{flags}\t{authors}\t{p.get('title') or '(untitled)'}"
        )
        n += 1
    print(f"\n{n} post(s).")


def export_posts(db, users, oids, out_dir, by_id, section):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written, missing = 0, []
    for oid in oids:
        p = db.post.find_one({"_id": oid})
        if not p:
            missing.append(str(oid))
            continue

        title = p.get("title") or "Untitled"
        slug = slugify(title)
        authors = resolve_authors(p, users)
        date_val = to_rfc3339(p.get("created_at"))

        lines = ["+++", f"title = {toml_str(title)}"]
        if date_val:
            lines.append(f"date = {date_val}")  # native TOML datetime (unquoted)
        lines.append(f"draft = {'true' if p.get('draft') else 'false'}")
        lines.append(f"slug = {toml_str(slug)}")
        if authors:
            lines.append(f"authors = {toml_str_array(authors)}")
        lines.append(f"aliases = {toml_str_array(['/' + section + '/' + str(oid)])}")
        lines.append(f"source_id = {toml_str(str(oid))}")
        lines.append("+++")
        lines.append("")
        front = "\n".join(lines)

        body = p.get("content") or ""
        fname = f"{str(oid)}.md" if by_id else f"{slug}.md"
        path = out_dir / fname
        if path.exists() and not by_id:
            path = out_dir / f"{slug}-{str(oid)[-6:]}.md"
        path.write_text(front + body + "\n")
        print(f"wrote {path}  (authors: {', '.join(authors) or 'none'})")
        written += 1

    print(f"\nDone. {written} file(s) written to {out_dir}/")
    if missing:
        print(f"NOT FOUND ({len(missing)}): {', '.join(missing)}")


def main():
    ap = argparse.ArgumentParser(
        description="List or export posts to Hugo content files."
    )
    ap.add_argument("ids", nargs="*", help="post ObjectIds to export")
    ap.add_argument("--list", action="store_true", help="list all posts and exit")
    ap.add_argument(
        "--public-only",
        action="store_true",
        help="with --list, show only public non-draft posts",
    )
    ap.add_argument(
        "--ids-file", help="file with one id per line (in addition to args)"
    )
    ap.add_argument("--uri", default="mongodb://localhost:27017")
    ap.add_argument("--db", default="rsvpdata")
    ap.add_argument(
        "--out", default="content/posts", help="output dir (default: content/posts)"
    )
    ap.add_argument(
        "--by-id", action="store_true", help="name files by id instead of slug"
    )
    ap.add_argument(
        "--section", default="posts", help="Hugo section for the alias (default: posts)"
    )
    args = ap.parse_args()

    client = MongoClient(args.uri)
    db = client[args.db]
    users = build_user_map(db)

    if args.list:
        list_posts(db, users, public_only=args.public_only)
        return

    raw_ids = list(args.ids)
    if args.ids_file:
        raw_ids += [
            ln.strip()
            for ln in Path(args.ids_file).read_text().splitlines()
            if ln.strip()
        ]
    if not raw_ids:
        ap.error(
            "no post IDs given. Use --list to browse, or pass IDs / --ids-file to export."
        )

    try:
        oids = [clean_id(r) for r in raw_ids]
    except ValueError as e:
        sys.exit(f"ERROR: {e}")

    export_posts(db, users, oids, args.out, args.by_id, args.section)


if __name__ == "__main__":
    main()
