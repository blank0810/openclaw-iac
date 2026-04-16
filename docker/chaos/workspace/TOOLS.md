# Tools

## gateway

Self-configuration interface. Read and patch own `openclaw.json`.

- `config.get(path)` — read a config key
- `config.patch(patches)` — apply a JSON Patch array to config
- Rejects bare arrays as `raw` — wrap in `{"op": "replace", "path": "/x", "value": [...]}`

## cron

Schedule recurring jobs. **Owner-gated** — callers must be listed in
`commands.ownerAllowFrom` (Slack user IDs prefixed `slack:`).

- `cron.add(id, schedule, prompt)` — schedule a new job
- `cron.list()` — list active jobs
- `cron.remove(id)` — delete a job

## memory

Persistent sqlite-backed memory.

- `memory.write(key, value)` — store a value
- `memory.read(key)` — retrieve
- `memory.search(query)` — semantic search across stored values

## web

Web search via SearXNG sidecar at `http://searxng:8080`.

- `web.search(query, n=10)` — returns JSON results
- `web.fetch(url)` — fetch a URL and return text

## image

Image generation via the provider configured in `openclaw.json`.

- `image.generate(prompt, size)` — returns an image URL or base64 blob
