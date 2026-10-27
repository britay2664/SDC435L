# Name: Brian Taylor
# Date: October 27, 2026
# Assignment: SDC435L Course Project Week 4
# Purpose: Connect GitHub Activity Explorer to Neo4j.
# Dataset import, interactive CRUD, and graph analysis will follow.

import io
import json
import zipfile
from pathlib import Path

from datetime import datetime
from getpass import getpass

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable


URI = "neo4j://127.0.0.1:7687"
DATABASE = "neo4j"

DATASET_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "GitHubArchive-Dataset.zip"
)
IMPORT_LIMIT = 5000
BATCH_SIZE = 250

def setup_graph(session):
    """Create uniqueness constraints for project nodes."""
    queries = [
        """
        CREATE CONSTRAINT sdc435l_repository_name IF NOT EXISTS
        FOR (r:SDC435LRepository) REQUIRE r.name IS UNIQUE
        """,
        """
        CREATE CONSTRAINT sdc435l_commit_hash IF NOT EXISTS
        FOR (c:SDC435LCommit) REQUIRE c.hash IS UNIQUE
        """,
        """
        CREATE CONSTRAINT sdc435l_contributor_id IF NOT EXISTS
        FOR (u:SDC435LContributor) REQUIRE u.id IS UNIQUE
        """,
        """
        CREATE CONSTRAINT sdc435l_language_name IF NOT EXISTS
        FOR (l:SDC435LLanguage) REQUIRE l.name IS UNIQUE
        """,
    ]

    for query in queries:
        session.run(query).consume()

    print("Project graph constraints are ready.")

def dataset_batches(archive, filename):
    """Read a limited JSON sample without extracting the ZIP."""
    batch = []
    count = 0

    with archive.open(filename) as source:
        with io.TextIOWrapper(source, encoding="utf-8") as lines:
            for line_number, line in enumerate(lines, start=1):
                if not line.strip():
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"{filename}, line {line_number}: invalid JSON"
                    ) from error

                if not isinstance(record, dict):
                    raise ValueError("Each dataset record must be an object.")

                batch.append(record)
                count += 1

                if len(batch) >= BATCH_SIZE:
                    yield batch
                    batch = []

                if count >= IMPORT_LIMIT:
                    break

    if batch:
        yield batch


def required_text(value, field):
    """Reject missing identifiers before writing nodes."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string.")
    return value.strip()


def write_repository_batch(tx, rows):
    """Create or update repositories by their unique names."""
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (r:SDC435LRepository {name: row.name})
        SET r.watch_count = row.watch_count
        """,
        rows=rows,
    ).consume()


def write_commit_batch(tx, rows):
    """Replace each imported commit's project relationships atomically."""
    # Remove old associations so reimport does not retain outdated links.
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (c:SDC435LCommit {hash: row.hash})
        MATCH (c)-[rel:SDC435L_IN_REPOSITORY]->
              (:SDC435LRepository)
        DELETE rel
        """,
        rows=rows,
    ).consume()

    tx.run(
        """
        UNWIND $rows AS row
        MATCH (:SDC435LContributor)-[rel:SDC435L_AUTHORED]->
              (c:SDC435LCommit {hash: row.hash})
        DELETE rel
        """,
        rows=rows,
    ).consume()

    tx.run(
        """
        UNWIND $rows AS row
        MERGE (c:SDC435LCommit {hash: row.hash})
        SET c.message = row.message, c.subject = row.subject

        MERGE (u:SDC435LContributor {id: row.author_id})
        SET u.name = row.author_name,
            u.identity_basis = row.identity_basis
        MERGE (u)-[:SDC435L_AUTHORED]->(c)

        FOREACH (repo_name IN row.repositories |
            MERGE (r:SDC435LRepository {name: repo_name})
            MERGE (c)-[:SDC435L_IN_REPOSITORY]->(r)
        )
        """,
        rows=rows,
    ).consume()


def write_language_batch(tx, rows):
    """Replace language relationships for each imported repository."""
    tx.run(
        """
        UNWIND $rows AS row
        MATCH (r:SDC435LRepository {name: row.name})
              -[rel:SDC435L_USES_LANGUAGE]->(:SDC435LLanguage)
        DELETE rel
        """,
        rows=rows,
    ).consume()

    tx.run(
        """
        UNWIND $rows AS row
        MERGE (r:SDC435LRepository {name: row.name})
        FOREACH (item IN row.languages |
            MERGE (l:SDC435LLanguage {name: item.name})
            MERGE (r)-[rel:SDC435L_USES_LANGUAGE]->(l)
            SET rel.bytes = item.bytes
        )
        """,
        rows=rows,
    ).consume()


def import_dataset(session):
    """Import repositories, commits, contributors, and languages."""
    if not DATASET_PATH.is_file():
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")

    sources = [
        ("repo", "GitHubArchive-Dataset/Sample_Repos.json"),
        ("commit", "GitHubArchive-Dataset/Commits.json"),
        ("language", "GitHubArchive-Dataset/Languages.json"),
    ]

    with zipfile.ZipFile(DATASET_PATH) as archive:
        for category, filename in sources:
            processed = 0

            for batch in dataset_batches(archive, filename):
                rows = []

                for record in batch:
                    if category == "repo":
                        count = int(record["watch_count"])
                        if not 0 <= count <= 9223372036854775807:
                            raise ValueError("Invalid watch count.")

                        rows.append({
                            "name": required_text(
                                record.get("repo_name"), "repo_name"
                            ),
                            "watch_count": count,
                        })

                    elif category == "commit":
                        commit_hash = required_text(
                            record.get("commit"), "commit"
                        )
                        author = record.get("author") or {}
                        name = author.get("name")
                        name = (
                            name.strip()
                            if isinstance(name, str) and name.strip()
                            else "(Unknown author)"
                        )

                        email = author.get("email")
                        email = (
                            email.strip()
                            if isinstance(email, str) else ""
                        )

                        # Shared names alone are not reliable identities.
                        # Without email, keep the author specific to this commit.
                        author_id = (
                            "email:" + email
                            if email else "commit:" + commit_hash
                        )

                        repositories = record.get("repo_name")
                        if not isinstance(repositories, list):
                            raise ValueError("Commit repo_name must be a list.")

                        repositories = sorted({
                            required_text(value, "repository name")
                            for value in repositories
                        })

                        message = record.get("message", "")
                        subject = record.get("subject", "")
                        if not isinstance(message, str):
                            raise ValueError("Commit message must be text.")
                        if not isinstance(subject, str):
                            raise ValueError("Commit subject must be text.")

                        rows.append({
                            "hash": commit_hash,
                            "author_id": author_id,
                            "author_name": name,
                            "identity_basis": (
                                "dataset email" if email
                                else "commit-specific fallback"
                            ),
                            "repositories": repositories,
                            "message": message,
                            "subject": subject,
                        })

                    else:
                        totals = {}

                        for item in record["language"]:
                            name = required_text(
                                item.get("name"), "language name"
                            )
                            byte_count = int(item["bytes"])
                            if byte_count < 0:
                                raise ValueError("Negative language bytes.")
                            totals[name] = totals.get(name, 0) + byte_count

                        if any(
                            count > 9223372036854775807
                            for count in totals.values()
                        ):
                            raise ValueError("Language bytes exceed integer range.")

                        rows.append({
                            "name": required_text(
                                record.get("repo_name"), "repo_name"
                            ),
                            "languages": [
                                {"name": name, "bytes": count}
                                for name, count in totals.items()
                            ],
                        })

                writer = {
                    "repo": write_repository_batch,
                    "commit": write_commit_batch,
                    "language": write_language_batch,
                }[category]

                session.execute_write(writer, rows)
                processed += len(rows)

            print(
                f"{Path(filename).name}: processed {processed:,} records.",
                flush=True,
            )

    print("Import complete. Matching nodes and associations were updated.")
    print("Results describe only the imported historical sample.")
    print("Contributor identity uses dataset email when available.")
    print("Email identities may still be shared or inconsistent.")
def ask_repository_name():
    """Validate an owner/repository identifier."""
    name = input("Repository name (owner/name): ").strip()
    parts = name.split("/")

    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ValueError("Enter a name such as britay2664/demo.")

    return name


def ask_watch_count():
    """Accept a nonnegative integer supported by Neo4j."""
    count = int(input("Watch count: ").strip())

    if not 0 <= count <= 9223372036854775807:
        raise ValueError("Enter a nonnegative 64-bit integer.")

    return count


def create_repository(session):
    """CREATE: Add a repository without overwriting an existing node."""
    name = ask_repository_name()
    count = ask_watch_count()

    # The uniqueness constraint rejects an existing repository name.
    session.run(
        """
        CREATE (r:SDC435LRepository {
            name: $name,
            watch_count: $count
        })
        """,
        name=name,
        count=count,
    ).consume()

    print("Repository created.")


def read_repository(session):
    """READ: Retrieve a project repository and its watch count."""
    name = ask_repository_name()

    record = session.run(
        """
        MATCH (r:SDC435LRepository {name: $name})
        RETURN r.name AS name, r.watch_count AS watch_count
        """,
        name=name,
    ).single()

    if record is None:
        print("Repository not found.")
    else:
        print(json.dumps(record.data(), indent=2))
        if record["watch_count"] is None:
            print("This repository has no imported watch count.")


def update_repository(session):
    """UPDATE: Change an existing repository's watch count."""
    name = ask_repository_name()
    count = ask_watch_count()

    record = session.run(
        """
        MATCH (r:SDC435LRepository {name: $name})
        SET r.watch_count = $count
        RETURN r.name AS name
        """,
        name=name,
        count=count,
    ).single()

    print("Repository updated." if record else "Repository not found.")


def delete_repository(session):
    """DELETE: Remove a project repository and its attached relationships."""
    name = ask_repository_name()

    print("Deletion also removes this repository's graph relationships.")
    print("Related contributor, commit, and language nodes remain.")

    if input(f"Delete '{name}'? Type YES: ").strip() != "YES":
        print("Deletion canceled.")
        return

    summary = session.run(
        """
        MATCH (r:SDC435LRepository {name: $name})
        DETACH DELETE r
        """,
        name=name,
    ).consume()

    print("Repository deleted." if summary.counters.nodes_deleted
          else "Repository not found.")

def repository_exists(session, name):
    """Check for the selected project repository."""
    record = session.run(
        """
        MATCH (r:SDC435LRepository {name: $name})
        RETURN r.name AS name
        """,
        name=name,
    ).single()

    if record is None:
        print("Repository not found.")
        return False

    return True


def repository_contributors(session):
    """Follow contributor-to-commit-to-repository relationships."""
    name = ask_repository_name()
    if not repository_exists(session, name):
        return

    records = session.run(
        """
        MATCH (u:SDC435LContributor)-[:SDC435L_AUTHORED]->
              (c:SDC435LCommit)-[:SDC435L_IN_REPOSITORY]->
              (r:SDC435LRepository {name: $name})
        RETURN u.id AS contributor_id,
               u.name AS contributor_name,
               u.identity_basis AS identity_basis,
               count(DISTINCT c) AS commits
        ORDER BY commits DESC, contributor_id
        LIMIT 20
        """,
        name=name,
    ).data()

    print(f"\nUp to 20 contributors associated with {name}")

    if not records:
        print("No contributor relationships found in the imported sample.")
        return

    for record in records:
        print(
            f"{record['contributor_name']}: "
            f"{record['commits']:,} commits "
            f"({record['identity_basis']})"
        )

    print("Contributor identities are dataset-based, not verified people.")


def repositories_with_shared_contributors(session):
    """Find other repositories linked to the same contributor nodes."""
    name = ask_repository_name()
    if not repository_exists(session, name):
        return

    records = session.run(
        """
        MATCH (source:SDC435LRepository {name: $name})
              <-[:SDC435L_IN_REPOSITORY]-(:SDC435LCommit)
              <-[:SDC435L_AUTHORED]-(u:SDC435LContributor)
        WITH DISTINCT source, u
        MATCH (u)-[:SDC435L_AUTHORED]->(:SDC435LCommit)
              -[:SDC435L_IN_REPOSITORY]->
              (other:SDC435LRepository)
        WHERE other <> source
        RETURN other.name AS repository,
               count(DISTINCT u) AS shared_contributors
        ORDER BY shared_contributors DESC, repository
        LIMIT 10
        """,
        name=name,
    ).data()

    print(f"\nRepositories sharing contributors with {name}")

    if not records:
        print("No shared contributors found in the imported sample.")
        return

    for record in records:
        print(
            f"{record['repository']}: "
            f"{record['shared_contributors']:,} shared contributor identities"
        )

    print("Shared identities do not prove direct collaboration.")


def repositories_with_shared_languages(session):
    """Find repositories connected to the same language nodes."""
    name = ask_repository_name()
    if not repository_exists(session, name):
        return

    records = session.run(
        """
        MATCH (source:SDC435LRepository {name: $name})
              -[:SDC435L_USES_LANGUAGE]->(l:SDC435LLanguage)
              <-[:SDC435L_USES_LANGUAGE]-
              (other:SDC435LRepository)
        WHERE other <> source
        WITH other, collect(DISTINCT l.name) AS languages
        RETURN other.name AS repository,
               languages,
               size(languages) AS shared_languages
        ORDER BY shared_languages DESC, repository
        LIMIT 10
        """,
        name=name,
    ).data()

    print(f"\nRepositories sharing languages with {name}")

    if not records:
        print("No shared languages found in the imported sample.")
        return

    for record in records:
        print(
            f"{record['repository']}: "
            f"{record['shared_languages']} shared language(s) — "
            + ", ".join(sorted(record["languages"]))
        )

    print("Shared languages do not establish similar purpose or code.")

def menu(session):
    """Route user selections to import and CRUD operations."""
    actions = {
        "1": lambda: import_dataset(session),
        "2": lambda: create_repository(session),
        "3": lambda: read_repository(session),
        "4": lambda: update_repository(session),
        "5": lambda: delete_repository(session),
        "6": lambda: repository_contributors(session),
        "7": lambda: repositories_with_shared_contributors(session),
        "8": lambda: repositories_with_shared_languages(session),
    }

    while True:
        print("\nNeo4j GitHub Activity Explorer")
        print(
            "System date and time:",
            datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        print("1. Import dataset")
        print("2. Create a repository")
        print("3. Read a repository")
        print("4. Update a repository")
        print("5. Delete a repository")
        print("6. View repository contributors")
        print("7. Find repositories with shared contributors")
        print("8. Find repositories with shared languages")
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
            action()
        except (
            Neo4jError,
            ServiceUnavailable,
            ValueError,
            OSError,
            zipfile.BadZipFile,
            KeyError,
            TypeError,
        ) as error:
            print(f"Operation failed: {error}")
            if choice == "1":
                print("Earlier import batches may already have been saved.")


def main():
    """Connect using credentials entered at runtime."""
    print("Neo4j GitHub Activity Explorer")
    print(
        "System date and time:",
        datetime.now().astimezone().isoformat(timespec="seconds"),
    )

    username = input("Neo4j username [neo4j]: ").strip() or "neo4j"
    password = getpass("Neo4j password: ")

    try:
        with GraphDatabase.driver(
            URI, auth=(username, password)
        ) as driver:
            driver.verify_connectivity()

            with driver.session(database=DATABASE) as session:
                result = session.run(
                    "RETURN 'Project connection successful!' AS message"
                )
                print(result.single()["message"])

                setup_graph(session)

                menu(session)

    except (Neo4jError, ServiceUnavailable) as error:
        print(f"Neo4j connection failed: {error}")


if __name__ == "__main__":
    main()
