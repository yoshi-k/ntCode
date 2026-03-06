# NL-to-SQL Tool

A command-line tool that converts **natural language queries into SQL** using the OpenAI API. Point it at any SQLite database, describe what you want in plain English, and get results back — no SQL knowledge required.

---

## Features

- 🔍 **Natural language to SQL** — powered by GPT-4o
- 🗄️ **Auto schema detection** — reads your SQLite database structure automatically
- 🖥️ **Interactive mode** — run multiple queries in a single session
- 📋 **Flexible output** — display results as a formatted table or JSON
- ⚡ **Simple CLI** — easy to use from the command line

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.10+ |
| LLM | OpenAI GPT-4o (via `openai` SDK) |
| Database | SQLite (built-in `sqlite3`) |
| CLI | `argparse` |
| Formatting | `tabulate` |

---

## Prerequisites

- Python 3.10 or higher
- An [OpenAI API key](https://platform.openai.com/api-keys)

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd <repo-directory>
   ```

2. **Install dependencies:**
   ```bash
   pip install openai tabulate
   ```

3. **Set your OpenAI API key:**
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   ```

---

## Usage

### Single Query

Run a one-off natural language query against your database:

```bash
python ntCode.py path/to/database.db --query "Show me all users who signed up last month"
```

### Interactive Mode

Start an interactive session to run multiple queries without restarting the tool:

```bash
python ntCode.py path/to/database.db --interactive
```

Type `exit` to quit the interactive session.

### Output Format

Results are displayed as a grid table by default. Switch to JSON output with `--format json`:

```bash
python ntCode.py path/to/database.db --query "List all products" --format json
```

### CLI Reference

```
python ntCode.py <db> [options]

positional arguments:
  db                    Path to the SQLite database file

options:
  -q, --query QUERY     Natural language query to run
  -i, --interactive     Run in interactive mode
  -f, --format FORMAT   Output format: table (default) or json
  -h, --help            Show this help message and exit
```

---

## Example

```
$ python ntCode.py mydata.db --query "How many orders were placed per customer?"

Generated SQL:
SELECT customer_id, COUNT(*) AS order_count FROM orders GROUP BY customer_id;

+---------------+-------------+
| customer_id   | order_count |
+===============+=============+
| 1             | 5           |
| 2             | 3           |
| 3             | 8           |
+---------------+-------------+
```

---

## How It Works

1. **Schema Detection** — Reads all tables and columns from your SQLite database.
2. **Prompt Building** — Constructs a prompt containing the schema and your natural language query.
3. **OpenAI Request** — Sends the prompt to GPT-4o, which returns a valid SQL query.
4. **SQL Execution** — Runs the generated SQL against the database.
5. **Result Formatting** — Displays the results as a table or JSON.

---

## Target Audience

Developers and data analysts who want to query SQLite databases without writing SQL manually.

---

## Future Enhancements

- Support for additional databases (PostgreSQL, MySQL)
- Query history and caching
- Web UI
- Multiple LLM backends (Anthropic, local models)

---

## License

MIT
