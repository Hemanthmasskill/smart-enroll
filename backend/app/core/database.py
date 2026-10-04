from pymongo import MongoClient

from app.core.config import settings

client: MongoClient | None = None


def connect_to_mongo():
    global client
    client = MongoClient(settings.MONGODB_URI)


def close_mongo_connection():
    global client
    if client is not None:
        client.close()
        client = None


def get_db():
    return client[settings.DATABASE_NAME]
