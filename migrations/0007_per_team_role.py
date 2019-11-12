def up(db):
    if db.team.count() == 0:
        team = {"_id": "default", "name": "Default Team"}
        db.team.insert_one(team)
    for user in db.user.find():
        roles = [{"name": role, "team": "default"} for role in user["roles"]]
        db.user.find_one_and_update(
            {"_id": user["_id"]}, {"$unset": {"roles": ""}}
        )
        db.user.find_one_and_update(
            {"_id": user["_id"]}, {"$set": {"roles": roles}}
        )


def down(db):
    db.team.delete_many({})
    for user in db.user.find():
        roles = [role["name"] for role in user["roles"]]
        db.user.find_one_and_update(
            {"_id": user["_id"]}, {"$unset": {"roles": ""}}
        )
        db.user.find_one_and_update(
            {"_id": user["_id"]}, {"$set": {"roles": roles}}
        )
