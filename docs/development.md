# Development

## Python environment

Use Python 3.8 or newer. A virtual environment is recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Open `http://127.0.0.1:8080`.

## Docker access

Docker Desk expects the local Docker Engine to be available through the Docker SDK's default environment. On a conventional Linux installation this is `/var/run/docker.sock`.

The application does not change socket permissions. Ensure the user running Docker Desk has appropriate Docker access before starting it. Docker socket access is highly privileged; keep the dashboard bound to localhost unless a future version adds an explicit security model.

## Testing

The test suite uses Flask's test client and a fake Docker SDK client, so it can validate route behavior without a running Docker Engine. A real Engine integration check should be performed on a Linux development machine with Docker running.

```bash
python -m unittest discover -s tests -v
```

## Debugging

Docker SDK connection errors are logged to the Flask process. The browser intentionally receives a short, non-sensitive error message rather than a Python traceback.

## Adding Docker data

1. Add the smallest necessary SDK access in `app.py`.
2. Keep the returned JSON plain and serializable.
3. Update the relevant Jinja/JavaScript rendering.
4. Update `docs/api.md` and README limitations if the behavior changes.
5. Add or update tests using the fake Docker client.

Do not add a new framework or persistence layer for a small data point.
