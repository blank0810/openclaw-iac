# Chaos Recovery Runbook

Use when Chaos is in a crash loop and you can't `docker exec` into it (container
dies before you can attach).

## Symptoms

- `docker ps -a` shows Chaos restarting every 10-30s
- `docker logs chaos` shows the same error on every attempt
- Likely cause: bot-authored config change broke startup

## Recovery steps

**1. Stop the crash loop:**

```bash
ssh -p 2222 -i hetzner-cloudesk.pem overlord101@<SERVER3_IP>
cd /opt/openclaw/chaos
docker compose stop chaos
```

**2. Inspect the broken config:**

```bash
sudo cat state/openclaw.json | jq .
```

**3. Restore from last backup:**

Fastest path: `scp scripts/restore-from-backup.sh` to the server once, then run `./restore-from-backup.sh` or `./restore-from-backup.sh --list`.

```bash
ls -lt /opt/openclaw/backups/ | head -5
sudo cp /opt/openclaw/backups/openclaw-YYYY-MM-DD.json state/openclaw.json
sudo chown 1000:1000 state/openclaw.json
sudo chmod 600 state/openclaw.json
```

**4. Start again:**

```bash
docker compose up -d chaos
docker logs -f chaos
```

**5. If backup is also broken — inspect with an entrypoint override:**

```bash
docker run --rm -it \
    -v /opt/openclaw/chaos/state:/home/node/.openclaw \
    -v /opt/openclaw/chaos/workspace:/home/node/.openclaw/workspace:ro \
    --entrypoint sh \
    ghcr.io/openclaw/openclaw:2026.4.14
# inside: inspect /home/node/.openclaw/openclaw.json, edit with vi, then exit.
```

**6. Nuclear option — reseed from repo:**

```bash
# On the server:
docker compose down chaos
sudo rm /opt/openclaw/chaos/state/openclaw.json /opt/openclaw/chaos/state/.seeded

# On your laptop:
cd ~/ai-project
source .venv/bin/activate
set -a; source .env; set +a
pyinfra --sudo -v infra/inventory.py infra/deploy.py
```

This re-triggers `chaos_seed.py` because the sentinel is gone.
