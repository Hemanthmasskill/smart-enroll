def get_application(db, applicant_id: str):
    return db["applications"].find_one({"applicantId": applicant_id}, {"_id": 0})


def create_application(db, application_data: dict):
    doc = application_data.copy()
    db["applications"].insert_one(doc)
    doc.pop("_id", None)
    return doc
