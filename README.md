# saidbtransport

`saidbtransport` copies an Oracle schema's tables and data into a local SQLite
database, checks the exported table row counts against Oracle, and can upload
the SQLite export to a Turso database. It also exports Oracle views when
exporting the whole schema; views that use SQL unsupported by SQLite are
reported and skipped.

## Requirements

- Python 3.9 or newer
- Oracle connection details and the wallet for the source database
- For upload: an existing Turso database and either the [Turso CLI](https://docs.turso.tech/cli/installation)
  logged in to your account, or a Turso database URL and auth token

## Setup

From the project directory, create and activate a virtual environment, then
install dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

Copy the example environment file and fill in the Oracle connection settings:

```sh
cp .env.example .env
```

Set `ORACLE_USER` and `ORACLE_PASSWORD`, `ORACLE_CONNECT_STRING` (or
`ORACLE_DSN`), and `ORACLE_WALLET_DIR` to the appropriate values. Set
`ORACLE_WALLET_PASSWORD` if the wallet requires it. `ORACLE_SCHEMA` is
optional; it defaults to `ORACLE_USER`. The wallet directory should contain
the Oracle wallet files, including `tnsnames.ora`.

The local SQLite output defaults to `export.db`. Change `SQLITE_PATH` in `.env`
or pass `--sqlite path/to/file.db` to a command to use another file.

## Export

Export all tables in the configured Oracle schema to SQLite:

```sh
python -m src export
```

The command asks for confirmation for each table when run interactively
(press Enter to include it). To select only specific tables:

```sh
python -m src export --tables TABLE_A TABLE_B
```

Specifying tables skips view export. Add `--yes` to automatically include all
selected tables. The command logs the number of rows exported for each table.

## Verify

Compare the row counts in Oracle and the local SQLite export:

```sh
python -m src verify
```

Verification reports each table's Oracle and SQLite row counts and exits with
a nonzero status if any counts differ. By default, it asks before checking each
table; use `--yes` to check all tables without prompts. Verification compares
row counts, not individual column values.

To verify only selected tables or use a different SQLite file:

```sh
python -m src verify --tables TABLE_A TABLE_B --sqlite path/to/file.db
```

## Upload

The destination Turso database must already exist. Install and authenticate the
[Turso CLI](https://docs.turso.tech/cli/installation), then set its name in
`.env`:

```dotenv
TURSO_DB_NAME=your-database-name
```

Alternatively, set `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` in `.env` to
connect without using the CLI to resolve the URL and token. `TURSO_DB_NAME` is
still required by the command.

Upload the local export:

```sh
python -m src upload
```

The uploader ensures the selected tables and indexes exist, then upserts rows
using primary keys. Tables without a primary key are replaced on upload. Views
in the SQLite export are also recreated in Turso. The command asks before
uploading each table when run interactively; use `--yes` to upload all tables.
Uploading requires network access and a valid Turso database URL and token.

## Run the full workflow

Export, verify, and upload in sequence:

```sh
python -m src all
```

Upload runs only if verification succeeds. Add `--yes` to accept all table
prompts:

```sh
python -m src all --yes
```

## Tests

Run the test suite with:

```sh
python -m pytest
```

## Sensitive files

Keep `.env`, the Oracle wallet, and exported database files private. They are
excluded from Git by `.gitignore`; do not commit credentials, wallet contents,
or exported data.
