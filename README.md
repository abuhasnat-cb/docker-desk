# Docker Desk

Docker Desk is a lightweight, read-only local dashboard for Linux Docker Engine. It replaces the need to repeatedly run several Docker CLI inspection commands by putting current Docker state on one dense screen.

## V0.1

- Flask + Jinja server-rendered dashboard
- Docker SDK for Python as the Docker Engine source of truth
- Docker connection status and system summary
- Container and image lists
- Compose project grouping from standard Compose labels
- Read-only API routes for system, containers, and images
- Graceful Docker connection failure handling
- Small vanilla JavaScript refresh loop

The V0.1 scope deliberately excludes database, authentication, React/Node, AI/LLM functionality, remote Docker hosts, and Docker mutation operations.

## Requirements

- Linux
- Python 3.8+
- Local Docker Engine
- Permission for the running user to access `/var/run/docker.sock` (or the Docker SDK's configured local endpoint)

The checked-in dependencies are Flask 3.1.3 and Docker SDK for Python 7.2.0. These versions were current stable releases when this implementation was prepared.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Then open:

```text
http://127.0.0.1:8080
```

The development server is intentionally bound to localhost. Do not expose Docker Desk publicly in V0.1.

## Docker permissions

Docker Desk does not change Linux permissions. The user running it must be able to access the Docker Engine socket. On common Linux installations this means membership in the `docker` group, or an equivalent setup. Granting Docker socket access is effectively highly privileged access to the Docker Engine, so treat Docker Desk as a local developer utility.

## Project structure

```text
docker-desk/
├── README.md
├── requirements.txt
├── .gitignore
├── app.py
├── templates/
│   └── dashboard.html
├── static/
│   ├── style.css
│   └── app.js
├── docs/
│   ├── architecture.md
│   ├── api.md
│   └── development.md
└── tests/
    └── test_app.py
```

## Current limitations

- The development environment used to build this repository does not have a Docker CLI or local Docker Engine, so real Engine data could not be verified here.
- V0.1 does not implement resource statistics, logs, search/filtering, or Docker actions.
- Browser polling is intentionally simple and conservative.
