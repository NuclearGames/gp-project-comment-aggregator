# Google Play Review Digest Telegram Bot (Ollama)

## Overview

This project collects Google Play reviews from the last 24 hours, clusters complaints into topics using a local Ollama model, stores digests and topic-grouped raw reviews in Redis, and sends a daily digest to Telegram. All AI inference runs locally via Ollama, so no external AI API key is required.

## Prerequisites

- Google Play service account with Android Publisher API access
- Telegram bot token and target chat ID
- Docker Engine with Docker Compose plugin

No cloud AI dependency is needed.

## Model selection

Set `OLLAMA_MODEL` in `.env` to choose the local model used for analysis.

- Recommended on CPU-only hosts: `llama3.2`
- Recommended on GPU hosts: `llama3.1:8b` or `mistral`

The `ollama-init` service automatically pulls the configured model on first `docker compose up`.

## Setup

1. Clone the repository.
2. Create environment file:
   ```bash
   cp .env.example .env
   ```
3. Place your Google Play service account file at `./secrets/service_account.json`.
4. Start everything:
   ```bash
   docker compose up -d
   ```

On first run, model download may take several minutes depending on model size and network speed.

## GPU acceleration

To enable GPU acceleration, uncomment the `deploy` block under the `ollama` service in `docker-compose.yml` and install `nvidia-container-toolkit` on the host.

## Running the worker manually

```bash
docker compose run --rm worker
```

## Telegram commands

| Command | Description |
| --- | --- |
| `/start` | Show bot intro and command help |
| `/digest` | Show today’s digest if available |
| `/topic <TopicName> <start>-<end>` | Show topic reviews within the requested range |

## Architecture

The stack runs with six services:

- **ollama**: local LLM inference service
- **ollama-init**: one-time model pull helper at startup
- **redis**: persistent data store for digest and per-topic review lists
- **worker**: daily fetch → analyze → store → notify pipeline
- **bot**: Telegram long-polling interface for `/digest` and `/topic`
- **scheduler**: cron runner that starts the worker container every day at 08:00 UTC

Redis key model:

- `digest:{YYYY-MM-DD}` → JSON topic list
- `topics:{YYYY-MM-DD}` → ordered Redis list of topic names
- `reviews:{YYYY-MM-DD}:{topic_slug}` → Redis list of JSON-encoded reviews
- All digest/topic/review keys are stored with a 30-day TTL (`2_592_000` seconds)
