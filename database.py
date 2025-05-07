from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017/")
db = client.dating_bot
users = db.users
old_profiles = db.old_profiles
