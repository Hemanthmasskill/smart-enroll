from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from app.core.config import settings

client: MongoClient | None = None


def connect_to_mongo():
    global client
    client = MongoClient(settings.MONGODB_URI)
    db = client[settings.DATABASE_NAME]
    db["users"].create_index("email", unique=True)

    # Ensure unique index on applicationId, resolving any legacy duplicate seed records if present
    try:
        db["applications"].create_index("applicationId", unique=True, sparse=True)
    except DuplicateKeyError:
        seen = set()
        for doc in db["applications"].find({}, sort=[("_id", -1)]):
            app_id = doc.get("applicationId")
            if app_id:
                if app_id in seen:
                    db["applications"].delete_one({"_id": doc["_id"]})
                else:
                    seen.add(app_id)
        db["applications"].create_index("applicationId", unique=True, sparse=True)

    # Ensure unique index on userId (one application per applicant)
    try:
        db["applications"].create_index("userId", unique=True, sparse=True)
    except DuplicateKeyError:
        seen = set()
        for doc in db["applications"].find({"userId": {"$exists": True, "$ne": None}}, sort=[("_id", -1)]):
            uid = doc.get("userId")
            if uid:
                if uid in seen:
                    db["applications"].delete_one({"_id": doc["_id"]})
                else:
                    seen.add(uid)
        db["applications"].create_index("userId", unique=True, sparse=True)

    # Ensure unique compound index on (applicationId, documentType) for documents
    try:
        db["documents"].create_index([("applicationId", 1), ("documentType", 1)], unique=True)
    except DuplicateKeyError:
        pass

    try:
        db["documents"].create_index("documentId", unique=True, sparse=True)
    except DuplicateKeyError:
        pass

    # Ensure storage directory exists
    try:
        settings.storage_path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def close_mongo_connection():
    global client
    if client is not None:
        client.close()
        client = None


def get_db():
    global client
    if client is None:
        connect_to_mongo()
    return client[settings.DATABASE_NAME]
