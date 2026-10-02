# Docker and FRP Guide

The project uses the following deployment architecture:

- `FastAPI` runs in the `api` container.
- The frontend and Nginx run in the `web` container.
- Ollama runs directly on the host, outside Docker.
- The FRP client runs on the host.
- Local application address: `127.0.0.1:25796`
- Current FRP address: `171.22.26.98:25796`

## Prerequisites

Install and start the following applications:

- Docker Desktop
- Ollama

Confirm that Ollama is running and the `bge-m3` model is available:

```powershell
ollama list
ollama pull bge-m3
```

The project root must contain a `.env` file with at least a valid
`GROQ_API_KEY`. Never commit `.env` to Git or share it with others.

## Open the project directory

Run commands in PowerShell from the project root:

```powershell
cd "E:\B Project\chat-with-unknown-data"
```

## First build and startup

Build the images and start the services:

```powershell
docker compose up -d --build
```

After the services are ready, open:

```text
http://127.0.0.1:25796
```

## Check service status

```powershell
docker compose ps
```

The `api` service should be `healthy`; the `web` service should be `running`
or `Up`.

## View logs

Follow logs from every service:

```powershell
docker compose logs -f
```

Follow only FastAPI logs:

```powershell
docker compose logs -f api
```

Follow only Nginx and frontend logs:

```powershell
docker compose logs -f web
```

Press `Ctrl+C` to stop following logs. This does not stop the containers.

## Stop and restart

Stop and remove the Compose containers without removing images or persistent
data:

```powershell
docker compose down
```

Start again without rebuilding:

```powershell
docker compose up -d
```

Restart running services:

```powershell
docker compose restart
```

## What should I run after changing code?

### Backend changes

After changing Python files in `api` or `pipeline`, run:

```powershell
docker compose up -d --build
```

Docker rebuilds the code layer. Unless `requirements.txt` changed, it normally
reuses the cached Python dependency layer.

### Frontend changes

The `frontend` directory is mounted directly into the Nginx container, so a
rebuild is usually unnecessary. Use `Ctrl+F5` to perform a full browser refresh.

If necessary, restart only the web service:

```powershell
docker compose restart web
```

### Dependency changes

After changing `requirements.txt`, run:

```powershell
docker compose up -d --build
```

Docker reruns the dependency installation layer and downloads new packages.

### Dockerfile or Compose changes

After changing `Dockerfile` or `compose.yaml`, also run:

```powershell
docker compose up -d --build
```

## How Docker layer caching works

The Dockerfile is broadly ordered as follows:

```text
Install operating-system packages    <- usually cached
Copy requirements.txt                <- usually cached
Install Python dependencies          <- usually cached
Copy api and pipeline source code    <- rebuilt after code changes
```

Because of this order, an ordinary code change does not redownload every
dependency.

Dependencies may be downloaded or rebuilt when:

- `requirements.txt` changes;
- an earlier Dockerfile step changes;
- the build uses `--no-cache`;
- the Docker build cache is cleared;
- the base Python image is removed; or
- the base image version changes, such as `python:3.12-slim`.

For normal builds, use:

```powershell
docker compose up -d --build
```

Use the following command only to diagnose caching problems because it rebuilds
every layer from scratch:

```powershell
docker compose build --no-cache
```

## Persistent data

The enrichment and embedding caches are mounted from the project's `.cache`
directory to `/app/.cache` in the container. They survive container removal and
rebuilding. Model logs are stored in a Docker volume. All of this data remains
available after:

```powershell
docker compose down
```

Avoid the following command during normal use because it removes the Docker
volume containing model logs. It does not remove the project's `.cache`
directory:

```powershell
docker compose down -v
```

## Connect to Ollama on the host

The FastAPI container connects to Ollama on Windows at:

```text
http://host.docker.internal:11434
```

This value is configured in `compose.yaml`. Do not expose the Ollama port
through FRP or directly to the internet.

If the API reports an Ollama connection error:

1. Confirm that Ollama is running.
2. Run `ollama list`.
3. Confirm that `bge-m3` has been downloaded.
4. Inspect the API logs:

   ```powershell
   docker compose logs -f api
   ```

## FRP connection

The current required configuration in `frpc.ini` is:

```ini
[ChatWithData]
type = tcp
local_ip = 127.0.0.1
local_port = 25796
remote_port = 25796
```

Traffic follows this path:

```text
171.22.26.98:25796
        | FRP
        v
127.0.0.1:25796
        | Docker/Nginx
        v
FastAPI and frontend
```

Complete startup sequence:

1. Start Ollama.
2. Start the containers:

   ```powershell
   docker compose up -d
   ```

3. Test `http://127.0.0.1:25796` locally.
4. Start the `frpc` program or its startup script.
5. Test `http://171.22.26.98:25796` from another device or network.

You can confirm that `remote_port` is available on the VPS only after FRP
connects successfully and the address works from an external network.

## Recommended everyday commands

After a backend change:

```powershell
docker compose up -d --build
docker compose logs -f api
```

To start the unchanged application:

```powershell
docker compose up -d
docker compose ps
```

To stop it:

```powershell
docker compose down
```

## Database connection notes

The application has no fixed internal database. It accepts Microsoft SQL Server
connections through the user interface.

If SQL Server runs on the same Windows host, use this hostname in the
application's connection string instead of `localhost` or `127.0.0.1`:

```text
host.docker.internal
```

For example:

```text
mssql+pyodbc://sa:password@host.docker.internal/database_name?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
```

Inside a container, `localhost` refers to the container itself, not the Windows
host.
