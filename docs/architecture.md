# Architecture

Docker Desk is intentionally a single lightweight Python application:

```text
Browser
   ↓
Flask + Jinja
   ↓
Docker SDK for Python
   ↓
Local Docker Engine
```

## Application boundary

`app.py` owns the Flask routes and the small amount of Docker data normalization needed by the UI. Jinja renders the initial dashboard. Vanilla JavaScript polls the three read-only JSON endpoints and refreshes the visible data without a full page reload.

There is no separate frontend application, build system, database, cache, or background worker.

## Docker as source of truth

Docker Engine state is read through the Docker SDK rather than invoking the Docker CLI with subprocesses. This keeps Docker access explicit and avoids parsing command-line output.

## No database

V0.1 is a current-state dashboard. Persisting Docker state would add infrastructure without serving the V0.1 goal. The dashboard reads the Engine when a page/API request arrives.

## Read-only boundary

The application only calls inspection/listing methods. No container/image mutation operation is exposed.

## Error handling

Docker SDK connection errors are caught at the Flask boundary. The browser receives a controlled unavailable state instead of a traceback, while useful diagnostics are logged to the server console.
