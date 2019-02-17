def up(db):
    posts = db.post.find()
    for post in posts:
        author = post.get("author")
        if not author:
            continue
        db.post.find_one_and_update(
            {"_id": post["_id"]}, {"$push": {"authors": author}}
        )
        db.post.find_one_and_update(
            {"_id": post["_id"]}, {"$unset": {"author": ""}}
        )


def down(db):
    posts = db.post.find()
    for post in posts:
        authors = post.get("authors")
        db.post.find_one_and_update(
            {"_id": post["_id"]}, {"$unset": {"authors": ""}}
        )
        if authors:
            db.post.find_one_and_update(
                {"_id": post["_id"]}, {"$set": {"author": authors[0]}}
            )
