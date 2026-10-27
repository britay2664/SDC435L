# GitHub Activity Explorer

**Author:** Brian Taylor
**Course:** SDC435L Advanced Databases Lab
**Project:** Week 1

A menu-driven Python application that imports GitHub Archive data into Redis and lets users create, read, update, and delete records.

## Current Features

- Import the first 5,000 records from each of three dataset files.
- Create repository, commit, and language records.
- Retrieve records by repository name or commit hash.
- Update records by replacing their JSON data.
- Delete individual records after confirmation.
- Display the top 10 stored repositories by historical watch count.
- Find stored commits by an author's full name.
- Display a repository's language breakdown by recorded bytes.

## Technology Requirements and Dependencies

- Ubuntu Linux, including Ubuntu through Windows Subsystem for Linux.
- Python 3 and the Python venv module.
- Redis Server running locally on port 6379.
- redis-py, listed in requirements.txt.
- GitHubArchive-Dataset.zip supplied through the course.

The application uses Redis database 5 and the key prefix `sdc435l:`.

## Dataset Setup

Create a `data` folder inside the project and place the course ZIP there:

    SDC435L/
        githubActivityExplorer.py
        README.md
        requirements.txt
        data/
            GitHubArchive-Dataset.zip

Keep the original ZIP filename. Extraction is not required.

The importer reads these files inside the ZIP:

- GitHubArchive-Dataset/Sample_Repos.json
- GitHubArchive-Dataset/Commits.json
- GitHubArchive-Dataset/Languages.json

The dataset and virtual environment are excluded from GitHub. Download the dataset separately from Canvas before importing.

## Installation and Running

From the project folder in Ubuntu:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
sudo systemctl start redis-server
redis-cli ping
python githubActivityExplorer.py
```

The connection check should return `PONG`.

If your Ubuntu environment does not use systemd, run `redis-server` in a separate terminal instead.

## Using the Application

Select a numbered menu option:

1. Import dataset
2. Create a record
3. Read a record
4. Update a record
5. Delete a record
6. Repository watch count ranking
7. Contributor commit lookup
8. Repository language breakdown
0. Exit

For record operations, enter `repo`, `commit`, or `language` as the category. Then enter the repository name or full commit hash.

Creation and updates require a JSON object. For example:

```json
{"repo_name": "britay2664/demo", "watch_count": "10"}
```

The identifier inside the JSON must match the identifier entered at the prompt. Updates replace the complete record. Deletion requires typing `YES`.

Importing again replaces records with matching keys.

## Testing Completed

- Imported 5,000 records from each source file, producing 15,000 project keys.
- Created and retrieved a test repository record.
- Updated its watch count and verified the change.
- Deleted the test record and verified it was absent.
- Displayed the top 10 repositories by recorded watch count.
- Found 167 stored commits matching Teddy Katz, displaying 20.
- Displayed 80 bytes of C for lemi136/puntovent.

## Limitations and Future Improvements

Results describe only the imported sample and historical dataset values. They do not represent live GitHub counts or all GitHub activity.

Contributor searches match author names, which may be shared by different people. Commit results are not chronological.

Future improvements include stronger validation of commit and language records, a configurable import limit, and Redis indexes to improve searches and rankings.


## Week 2 MongoDB Application

`mongoActivityExplorer.py` imports GitHub Archive data into the
`SDC435L_GitHubArchive` MongoDB database and provides an interactive
menu for creating, reading, updating, and deleting documents.

### Requirements

- Python 3
- MongoDB Server running locally on port 27017
- PyMongo, listed in requirements.txt
- The course dataset at data/GitHubArchive-Dataset.zip

Tested on Windows using PowerShell and a Python virtual environment.

### Setup and Running on Windows

```powershell
py -m venv .venv-windows
.\.venv-windows\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-windows\Scripts\python.exe .\mongoActivityExplorer.py
```

Start MongoDB before running the application. The default connection
is mongodb://localhost:27017/. An optional MONGO_URI environment
variable can supply a different connection string.

Select option 1 to import the first 5,000 records from each of
Sample_Repos.json, Commits.json, and Languages.json. Reimporting
replaces matching documents using stable identifiers.

### Current Features

- Interactive document CRUD with validation and deletion confirmation.
- Five shortest and longest repository names using MongoDB aggregation.
- Repository watch count distribution using MongoDB aggregation.
- Top 15 commit message words using Python word counts.

Updates replace the complete document. Repository names identify
repository and language records; full commit hashes identify commits.

### Testing Completed

- Imported 15,000 documents across three collections.
- Created and retrieved a test repository.
- Updated its watch count from 10 to 25 and verified the change.
- Deleted the test repository and verified it was absent.
- Tested all three analysis features.
- Watch count distribution included 5,000 repositories.
- Word frequency analyzed 5,000 commit messages.

### Analysis Limitations

Results describe the imported historical sample, not all GitHub
repositories or current activity. Repository name lengths include
the owner name and slash. Word counts include repeated occurrences
and may include words from URLs or commit metadata. Percentages
may not total exactly 100% because of rounding.

## Week 3 Cassandra Application

`cassandraActivityExplorer.py` imports GitHub Archive data into Cassandra
and provides interactive repository CRUD and three analysis features.

### Requirements

- Ubuntu Linux, including Ubuntu through WSL
- Python 3.11 with venv support
- Cassandra running locally on port 9042
- A valid Cassandra username and password
- cassandra-driver 3.30.1
- Course dataset at data/GitHubArchive-Dataset.zip

### Setup and Running

```bash
python3.11 -m venv .venv-cassandra
source .venv-cassandra/bin/activate
python -m pip install -r requirements-cassandra.txt
python cassandraActivityExplorer.py
```

Start Cassandra before running the application. Enter your Cassandra
credentials at the prompts. Passwords are not stored in the source code.

The application creates the sdc435l_github_archive keyspace and four
tables: repositories, commits, languages, and commits_by_author.
The account must be allowed to create and access these objects.

The keyspace uses SimpleStrategy with replication factor 1 for this
single-node local lab.

### Current Features

1. Import dataset
2. Create a repository
3. Read a repository
4. Update a repository watch count
5. Delete a repository after confirmation
6. Rank repositories by stored commit count
7. Look up commits by exact author name
8. Display a repository's language breakdown
0. Exit

The importer processes the first 5,000 records from Sample_Repos.json,
Commits.json, and Languages.json directly from the ZIP. Reimporting
updates matching primary keys. Missing author names are labeled
(Unknown author).

Repository CRUD uses primary-key queries and conditional writes.
The commits_by_author table supports direct author partition lookups.
Language breakdown uses the repository primary key. Commit ranking
scans stored commits and counts repository associations in Python.

### Testing Completed

- Imported 5,000 records from each of the three source files.
- Created and read britay2664/demo with watch count 10.
- Updated the count to 25 and verified the change.
- Deleted the test repository and confirmed it was absent.
- Ranked repository associations from 5,000 stored commits.
- Retrieved 167 commits for Teddy Katz, displaying the first 20.
- Retrieved 80 bytes of C for lemi136/puntovent.
- Passed Python syntax compilation.

### Limitations and Future Improvements

Results describe the imported historical sample, not current trends.
A commit can belong to multiple repositories. Author names are
case-sensitive and may be shared by different people.

Ranking performs a sample-wide scan and is intended for this lab.
Larger datasets would need a different approach to maintaining rankings.
Author lookup entries are written separately from main commit records;
an interrupted import may require a successful rerun to restore agreement.

Future improvements include configurable import limits, stronger input
validation, and improved recovery for interrupted imports.

## Week 4 Neo4j Application

`neo4jActivityExplorer.py` imports GitHub Archive data into a graph
and provides interactive repository CRUD and relationship analysis.

### Requirements

- Python 3.10 or newer
- A running local Neo4j instance supporting uniqueness constraints
- Neo4j Python driver 6.4.1
- A Neo4j account permitted to create constraints and read/write data
- Course dataset at data/GitHubArchive-Dataset.zip

Tested on Windows using PowerShell. The application connects to
neo4j://127.0.0.1:7687 and uses the neo4j database.
Credentials are entered at runtime.

### Setup and Running

From the project folder:

```powershell
py -m venv .venv-windows
.\.venv-windows\Scripts\python.exe -m pip install -r requirements-neo4j.txt
.\.venv-windows\Scripts\python.exe .\neo4jActivityExplorer.py
```

Start the local Neo4j instance before running the application.
Select option 1 on the first run to import the dataset.
Keep the original dataset ZIP filename; extraction is unnecessary.

### Graph Structure

Project node labels:

- SDC435LRepository
- SDC435LCommit
- SDC435LContributor
- SDC435LLanguage

Project relationships:

- Contributor -[SDC435L_AUTHORED]-> Commit
- Commit -[SDC435L_IN_REPOSITORY]-> Repository
- Repository -[SDC435L_USES_LANGUAGE]-> Language

Language relationships store recorded byte counts.
Uniqueness constraints identify repositories, commits, contributors,
and languages. Project queries use these distinct labels.

### Current Features

1. Import dataset
2. Create a repository
3. Read a repository
4. Update a repository watch count
5. Delete a repository after confirmation
6. List contributors associated with a repository
7. Find repositories sharing contributor identities
8. Find repositories sharing programming languages
0. Exit

The importer processes the first 5,000 records from each of
Sample_Repos.json, Commits.json, and Languages.json.
Writes use batches of 250 records and parameterized Cypher queries.

Reimporting matches existing nodes and replaces imported commit
and language associations within each batch transaction.
It does not remove all nodes absent from the current import.

Repository creation rejects duplicate names. Updates affect existing
repositories only. Deletion removes the selected repository and its
attached relationships, leaving related nodes.

### Testing Completed

- Connected successfully and created graph constraints.
- Imported 5,000 records from each of the three source files.
- Created and read britay2664/demo with watch count 10.
- Updated the watch count to 25 and verified the change.
- Deleted the test repository and verified it was absent.
- Tested all three graph analysis options successfully.

### Limitations and Future Improvements

Results describe the imported historical sample, not current GitHub
activity. Contributor identity uses dataset email where available.
Without email, the application uses a commit-specific fallback.
Email identities may still be shared or inconsistent.

Shared contributors do not prove direct collaboration. Shared languages
do not establish similar code or purpose. Some repositories introduced
by commit or language records have no recorded watch count.

Import batches commit separately, so interrupted imports can leave
partial data. Unconnected contributor and language nodes may remain
after associations are replaced.

Future improvements include configurable import limits, stronger
validation, improved identity handling, and graph visualization.