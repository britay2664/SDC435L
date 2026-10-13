# Name: Brian Taylor
# Date: October 13, 2026
# Assignment: SDC435L Course Project Week 2
# Purpose: Import GitHub Archive data into MongoDB, provide interactive
# CRUD operations, and analyze repository names, watch counts,
# and common words in commit messages.

import copy
import io
import json
import os
import re
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from bson import json_util
from pymongo import MongoClient, ReplaceOne
from pymongo.errors import PyMongoError


PROJECT_FOLDER = Path(__file__).resolve().parent
DATASET_PATH = PROJECT_FOLDER / "data" / "GitHubArchive-Dataset.zip"
DATABASE_NAME = "SDC435L_GitHubArchive"
IMPORT_LIMIT = 5000

# An environment variable allows connection settings without storing
# credentials in the source code.
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")

COLLECTIONS = {
    "repo": "repositories",
    "commit": "commits",
    "language": "languages",
}


def show_time():
    """Display the local system date and time."""
    print("System date and time:",
          datetime.now().astimezone().isoformat(sep=" ", timespec="seconds"))


def choose_collection(database):
    """Ask for the record category and return its collection."""
    category = input(
        "Record category (repo, commit, language): "
    ).strip().lower()

    if category not in COLLECTIONS:
        raise ValueError("Choose repo, commit, or language.")

    return category, database[COLLECTIONS[category]]


def record_identifier():
    """Repository records use names; commit records use full hashes."""
    identifier = input(
        "Repository name or full commit hash: "
    ).strip()

    if not identifier:
        raise ValueError("The identifier cannot be empty.")

    return identifier


def prepare_record(category, record):
    """Validate records and assign a stable MongoDB document ID."""
    if not isinstance(record, dict):
        raise ValueError("Each record must be a JSON object.")

    document = copy.deepcopy(record)
    field = "commit" if category == "commit" else "repo_name"
    identifier = document.get(field)

    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError(f"'{field}' must be a nonempty string.")

    identifier = identifier.strip()
    document[field] = identifier

    if "_id" in document and document["_id"] != identifier:
        raise ValueError("'_id' must match the record identifier.")

    document["_id"] = identifier

    if category == "repo":
        # Store watch counts as integers for numeric aggregation.
        count = document.get("watch_count")
        if isinstance(count, bool) or not isinstance(count, (str, int)):
            raise ValueError("watch_count must be a nonnegative integer.")

        try:
            count = int(count)
        except ValueError as error:
            raise ValueError("watch_count must be an integer.") from error

        if count < 0:
            raise ValueError("watch_count cannot be negative.")

        document["watch_count"] = count

    elif category == "commit":
        author = document.get("author")
        if not isinstance(author, dict):
            raise ValueError("author must be an object.")

        if not isinstance(author.get("name"), str):
            raise ValueError("author.name must be a string.")

        if not isinstance(document.get("message"), str):
            raise ValueError("message must be a string.")

        repositories = document.get("repo_name")
        if (
            not isinstance(repositories, list)
            or not all(isinstance(name, str) for name in repositories)
        ):
            raise ValueError("repo_name must be a list of repository names.")

    elif category == "language":
        languages = document.get("language")
        if not isinstance(languages, list):
            raise ValueError("language must be a list.")

        for item in languages:
            if not isinstance(item, dict):
                raise ValueError("Each language entry must be an object.")

            if not isinstance(item.get("name"), str):
                raise ValueError("Each language needs a name.")

            byte_count = item.get("bytes")
            if (
                isinstance(byte_count, bool)
                or not isinstance(byte_count, (str, int))
            ):
                raise ValueError("Language bytes must be an integer.")

            try:
                byte_count = int(byte_count)
            except ValueError as error:
                raise ValueError("Language bytes must be an integer.") from error

            if byte_count < 0:
                raise ValueError("Language bytes cannot be negative.")

            item["bytes"] = byte_count

    return document


def input_record(category, identifier):
    """Read a complete JSON document for creation or replacement."""
    text = input("Enter the record as a JSON object on one line: ")
    document = prepare_record(category, json.loads(text))

    if document["_id"] != identifier:
        raise ValueError("The JSON identifier must match your entered identifier.")

    return document


def display_document(document):
    """Format documents using BSON-aware JSON serialization."""
    print(json_util.dumps(document, indent=2))


def import_dataset(database):
    """Stream a limited sample from the ZIP into three collections."""
    if not DATASET_PATH.is_file():
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")

    sources = [
        ("repo", "GitHubArchive-Dataset/Sample_Repos.json"),
        ("commit", "GitHubArchive-Dataset/Commits.json"),
        ("language", "GitHubArchive-Dataset/Languages.json"),
    ]

    # Upserts replace matching documents, making repeated imports safe.
    with zipfile.ZipFile(DATASET_PATH) as archive:
        for category, filename in sources:
            collection = database[COLLECTIONS[category]]
            operations = []
            count = 0

            with archive.open(filename) as source:
                with io.TextIOWrapper(source, encoding="utf-8") as lines:
                    for line_number, line in enumerate(lines, start=1):
                        if not line.strip():
                            continue

                        try:
                            document = prepare_record(
                                category, json.loads(line)
                            )
                        except (ValueError, TypeError) as error:
                            raise ValueError(
                                f"{filename}, line {line_number}: {error}"
                            ) from error

                        operations.append(
                            ReplaceOne(
                                {"_id": document["_id"]},
                                document,
                                upsert=True,
                            )
                        )
                        count += 1

                        # Write batches rather than retaining the full file.
                        if len(operations) >= 500:
                            collection.bulk_write(operations, ordered=True)
                            operations.clear()

                        if count >= IMPORT_LIMIT:
                            break

            if operations:
                collection.bulk_write(operations, ordered=True)

            print(f"{Path(filename).name}: processed {count:,} records.")

    print("Import complete. Matching documents were replaced.")
    print("Results describe only the imported sample.")
    for collection_name in COLLECTIONS.values():
        total = database[collection_name].count_documents({})
        print(f"{collection_name}: {total:,} documents")


# CREATE: Insert a user-provided document without replacing existing data.
def create_record(database):
    category, collection = choose_collection(database)
    identifier = record_identifier()
    document = input_record(category, identifier)
    collection.insert_one(document)
    print("Record created.")


# READ: Retrieve a specific document using its stable _id.
def read_record(database):
    _, collection = choose_collection(database)
    identifier = record_identifier()
    document = collection.find_one({"_id": identifier})

    if document is None:
        print("Record not found.")
    else:
        display_document(document)


# UPDATE: Replace a specific document while preserving its identifier.
def update_record(database):
    category, collection = choose_collection(database)
    identifier = record_identifier()
    existing = collection.find_one({"_id": identifier})

    if existing is None:
        print("Record not found.")
        return

    print("Current record:")
    display_document(existing)
    print("Enter the complete replacement record.")
    document = input_record(category, identifier)
    result = collection.replace_one({"_id": identifier}, document)

    if result.matched_count:
        print("Record updated." if result.modified_count
              else "Record already matches the supplied data.")
    else:
        print("Record no longer exists.")


# DELETE: Remove only the selected record after confirmation.
def delete_record(database):
    _, collection = choose_collection(database)
    identifier = record_identifier()

    confirmation = input(
        f"Delete '{identifier}'? Type YES: "
    ).strip()

    if confirmation != "YES":
        print("Deletion canceled.")
        return

    result = collection.delete_one({"_id": identifier})
    print("Record deleted." if result.deleted_count else "Record not found.")


# FEATURE 1: Use MongoDB aggregation to compare repository name lengths.
def repository_name_lengths(database):
    collection = database["repositories"]

    base_pipeline = [
        {"$match": {"repo_name": {"$type": "string"}}},
        {
            "$project": {
                "_id": 0,
                "repo_name": 1,
                "length": {"$strLenCP": "$repo_name"},
            }
        },
    ]

    if collection.count_documents({}) == 0:
        print("No repository records stored. Import data first.")
        return

    print("\nFive shortest stored repository names")
    for document in collection.aggregate(
        base_pipeline
        + [{"$sort": {"length": 1, "repo_name": 1}}, {"$limit": 5}]
    ):
        print(f"{document['repo_name']}: {document['length']} characters")

    print("\nFive longest stored repository names")
    for document in collection.aggregate(
        base_pipeline
        + [{"$sort": {"length": -1, "repo_name": 1}}, {"$limit": 5}]
    ):
        print(f"{document['repo_name']}: {document['length']} characters")

    print("Length includes the owner name and slash.")


# FEATURE 2: Group historical watch counts using MongoDB $bucket.
def watch_count_distribution(database):
    pipeline = [
        {
            "$match": {
                "watch_count": {"$type": "number", "$gte": 0}
            }
        },
        {
            "$bucket": {
                "groupBy": "$watch_count",
                "boundaries": [0, 10, 100, 1000, 10000],
                "default": "10000+",
                "output": {"repositories": {"$sum": 1}},
            }
        },
    ]

    counts = {
        document["_id"]: document["repositories"]
        for document in database["repositories"].aggregate(pipeline)
    }
    total = sum(counts.values())

    if total == 0:
        print("No valid watch counts stored. Import data first.")
        return

    print("\nRepository distribution by recorded watch count")
    for boundary, label in [
        (0, "0–9"),
        (10, "10–99"),
        (100, "100–999"),
        (1000, "1,000–9,999"),
        ("10000+", "10,000+"),
    ]:
        count = counts.get(boundary, 0)
        print(f"{label}: {count:,} repositories ({count / total:.1%})")

    print(f"Total included: {total:,}")
    print("These are historical dataset counts, not live GitHub counts.")


# FEATURE 3: Analyze common words in stored commit messages.
def commit_word_frequency(database):
    stop_words = {
        "a", "an", "and", "are", "as", "at", "be", "by", "for",
        "from", "in", "is", "it", "of", "on", "or", "that", "the",
        "this", "to", "was", "with",
    }

    frequency = Counter()
    message_count = 0

    # A projection retrieves only the message field needed for this feature.
    cursor = database["commits"].find(
        {"message": {"$type": "string"}},
        {"_id": 0, "message": 1},
    )

    for document in cursor:
        message_count += 1
        words = re.findall(r"[a-z]+", document["message"].lower())
        frequency.update(
            word for word in words
            if len(word) >= 3 and word not in stop_words
        )

    if not frequency:
        print("No usable commit message words found.")
        return

    print("\nTop 15 words in stored commit messages")
    for rank, (word, count) in enumerate(
        frequency.most_common(15), start=1
    ):
        print(f"{rank}. {word}: {count:,}")

    print(f"Messages analyzed: {message_count:,}")
    print("Counts represent word occurrences, including repeats.")
    print("Common stop words and words shorter than three letters are excluded.")
    print("Results describe only stored messages.")


def menu(database):
    """Route each menu selection to its operation."""
    actions = {
        "1": import_dataset,
        "2": create_record,
        "3": read_record,
        "4": update_record,
        "5": delete_record,
        "6": repository_name_lengths,
        "7": watch_count_distribution,
        "8": commit_word_frequency,
    }

    while True:
        print("\nMongoDB GitHub Activity Explorer")
        show_time()
        print("1. Import dataset")
        print("2. Create a record")
        print("3. Read a record")
        print("4. Update a record")
        print("5. Delete a record")
        print("6. Repository name lengths")
        print("7. Watch count distribution")
        print("8. Commit message word frequency")
        print("0. Exit")

        choice = input("Select an option: ").strip()

        if choice == "0":
            print("Program ended.")
            return

        action = actions.get(choice)
        if action is None:
            print("Choose an option from 0 through 8.")
            continue

        try:
            action(database)
        except (
            PyMongoError,
            ValueError,
            OSError,
            zipfile.BadZipFile,
            KeyError,
        ) as error:
            print(f"Operation failed: {error}")
            if choice == "1":
                print("Earlier import batches may already have been saved.")


def main():
    """Connect to MongoDB and close the client when finished."""
    client = None
    print("MongoDB GitHub Activity Explorer")
    show_time()

    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        database = client[DATABASE_NAME]
        print(f"Connected to MongoDB database {DATABASE_NAME}.")
        menu(database)

    except PyMongoError as error:
        print(f"MongoDB connection or operation failed: {error}")
        print("Check that MongoDB is running and MONGO_URI is correct.")

    except (KeyboardInterrupt, EOFError):
        print("\nProgram stopped.")

    finally:
        if client is not None:
            client.close()
        show_time()


if __name__ == "__main__":
    main()