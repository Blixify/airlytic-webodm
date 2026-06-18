# Deploying airlytic-webodm to <webodm-host>

Operational playbook for shipping changes from this fork to the production WebODM instance at `https://<webodm-host>` (single host, SSL via certbot, behind no proxy).

For verifying behaviour after a deploy, the airlytic-nextjs repo ships `scripts/test-webodm-filters.mjs` — a Node 18 predicate suite that hits the WebODM API end-to-end. Layer A covers health (JWT, baseline, has_tasks split, pagination envelope, Swagger); Layer B covers filter behaviour (`?tags=`, `?search=` over name / description / tag values). Exit 1 on any FAIL.

---

## The recommended path — minimal downtime

Use this for any change that touches `app/api/**`, `app/views/**`, or other server-side Python. It rebuilds only the `webapp` image while the rest of the stack keeps running, so **in-flight NodeODM processing tasks survive the deploy**.

### 1. Merge to master on GitHub

```bash
gh pr merge <PR#> --merge --repo Blixify/airlytic-webodm
```

### 2. SSH to the server and pull master

```bash
ssh <user>@<webodm-host>
cd ~/airlytic-webodm
git pull origin master
git log -1 --oneline   # confirm the new commit is HEAD
```

### 3. Rebuild only the webapp image (no downtime during this step)

```bash
docker-compose -f docker-compose.yml -f docker-compose.build.yml build webapp
```

Old containers keep serving while the new image bakes. Takes ~5–15 minutes the first time.

### 4. Swap the webapp container (~15–30s API downtime)

```bash
docker-compose stop webapp worker
docker-compose rm -f webapp worker
./webodm.sh start --ssl --hostname <webodm-host> --detached
```

Both `webapp` and `worker` use the same docker image (`opendronemap/webodm_webapp`). When you rebuild that image, docker-compose will try to recreate **both** containers on the next `up` and will hit the docker-compose 1.29 `'ContainerConfig'` bug on either of them. The `stop` + `rm` of both up front is the workaround. Worker downtime is brief (~15–30s) and any in-flight Celery task (upload to a node, download of results) is re-queued automatically by the broker on restart. NodeODM nodes themselves are not touched, so in-progress OpenDroneMap pipelines on a node keep running.

`./webodm.sh start --ssl` is required (not bare `docker-compose up`) because the SSL volume mounts and `WO_SSL_*` env vars are wired in by the wrapper script.

> If you originally provisioned SSL with explicit cert paths instead of the built-in `--ssl` flag, substitute:
> ```bash
> ./webodm.sh start \
>   --hostname <webodm-host> \
>   --ssl-key /etc/letsencrypt/live/<webodm-host>/privkey.pem \
>   --ssl-cert /etc/letsencrypt/live/<webodm-host>/fullchain.pem \
>   --port 443 \
>   --ssl-insecure-port-redirect 80 \
>   --detached
> ```

### 5. Verify

```bash
docker logs -f webapp 2>&1 | tail -30
# wait for: "Quit the server with CONTROL-C."
```

```bash
curl -ks https://<webodm-host>/api/projects/?page=1 -o /dev/null -w "%{http_code}\n"
# expect: 200
```

From the airlytic-nextjs repo on your laptop:

```bash
cd ~/Documents/Work.nosync/Airlytic/airlytic-nextjs
set -a && source .env && set +a
node scripts/test-webodm-filters.mjs
# expect: "13 passed, 0 failed"
```

### Impact summary

| Component | Affected? |
|---|---|
| webapp (Django + nginx) | ✅ Restarts (~15–30s downtime) |
| worker (Celery) | ❌ Not touched |
| db (Postgres) | ❌ Not touched |
| broker (Redis) | ❌ Not touched |
| node-odm (processing engine) | ❌ Not touched — in-flight tasks keep running |

---

## The full-restart path — use sparingly

For changes that touch the worker, NodeODM nodes, the Dockerfile itself, or shared docker-compose config. This brings everything down, including in-flight processing tasks.

```bash
git pull origin master
./webodm.sh rebuild
./webodm.sh start --ssl --hostname <webodm-host> --detached
```

`./webodm.sh rebuild` runs `docker-compose down --remove-orphans`, wipes `node_modules/`, and rebuilds with `--no-cache`. Expect 10–30 minutes total downtime and **all running OpenDroneMap processing tasks will be killed**.

Avoid when any task is in a non-resumable processing stage. The `liveupdate` command in `webodm.sh` is a less-aggressive alternative (`docker-compose pull` only) but it won't pick up code in this fork because we build locally rather than pulling from a registry.

---

## SSL — first-time setup vs. renewals

This instance uses Let's Encrypt via `webodm.sh --ssl`, which runs `nginx/letsencrypt-autogen.sh` to fetch a cert with `certbot certonly --standalone --http-01-port 8080`. The cert is stored at `./letsencrypt/live/<webodm-host>/` and symlinked into `./ssl/key.pem` and `./ssl/cert.pem`.

**First-time setup or after a server rebuild** — when certs are missing entirely:

```bash
./webodm.sh restart --ssl --hostname <webodm-host> --detached
```

`restart` does `down` + `start`, which is required on first setup so certbot can bind port 80 for the HTTP-01 challenge. Ports 80 and 443 must be open in the firewall / cloud security group.

**Renewals** — handled automatically by `webodm.sh --ssl` on every restart (the `--keep` flag inside the autogen script reuses still-valid certs and renews when within 30 days of expiry). Nothing else to do.

**Using system certbot instead** — pass `--ssl-key` and `--ssl-cert` explicitly (see step 4 above). The container reads the cert files at the host paths; ensure they're readable by docker (certbot's default `600` on `privkey.pem` may need `chmod 644`, which certbot will reset on the next renewal — re-apply in a post-renewal hook if you go this route).

---

## Troubleshooting

### `ERROR: for webapp 'ContainerConfig'` / `ERROR: for worker 'ContainerConfig'` during `docker-compose up`

Known docker-compose 1.29.2 bug with newer Docker Engine — the `ContainerConfig` key was removed from image metadata. Only triggers on the **recreate** path. Hits both `webapp` and `worker` because they share the same image. Workaround (stop + rm both up front):

```bash
docker-compose stop webapp worker
docker-compose rm -f webapp worker
./webodm.sh start --ssl --hostname <webodm-host> --detached
```

Long-term fix: install Docker Compose V2 (the Go-based plugin, invoked as `docker compose` without the hyphen) and switch the deploy commands.

### `https://<webodm-host>` returns ERR_CONNECTION_REFUSED after a restart

Most often: webapp was started bypassing `./webodm.sh start --ssl` (e.g. a bare `docker-compose up`) so the SSL volume mounts and `WO_SSL_*` env vars never landed in the container. Recovery:

```bash
docker-compose stop webapp
docker-compose rm -f webapp
./webodm.sh start --ssl --hostname <webodm-host> --detached
```

If certs are entirely missing on the host:

```bash
sudo certbot certificates                         # list known certs
sudo find / -name "fullchain.pem" 2>/dev/null     # find any stray copies
```

If certbot has none, re-run the first-time setup path above (`./webodm.sh restart --ssl --hostname <webodm-host> --detached`) — autogen will fetch a fresh cert.

### Container stops as soon as the SSH session closes

`./webodm.sh start` without `--detached` runs docker-compose attached to your terminal — Ctrl+C (or shell exit) sends SIGINT to containers. Always include `--detached` in production. Verify with `docker ps` after disconnecting; safe to `docker logs -f webapp` afterward (Ctrl+C on a log tail does **not** stop the container).

### Plugin warnings on startup

```
WARNING Failed to instantiate plugin pagination_plugin: No module named 'coreplugins.pagination_plugin'
WARNING Failed to instantiate plugin optimization-plugin: invalid syntax (plugin.py, line 43): None
```

Pre-existing on this fork; not caused by any recent PR. Investigate when you have time, but they don't block deploys.

---

## Rollback

If a deploy breaks the API (e.g. a filter raises 500), revert and redeploy:

```bash
git revert HEAD --no-edit
git push origin master
docker-compose -f docker-compose.yml -f docker-compose.build.yml build webapp
docker-compose stop webapp
docker-compose rm -f webapp
./webodm.sh start --ssl --hostname <webodm-host> --detached
```

Then re-run `node scripts/test-webodm-filters.mjs` from airlytic-nextjs to confirm green.

---

## Pre-deploy checklist

- [ ] PR is merged to `master` (verify with `git log origin/master -1`)
- [ ] No new database migrations? (this fork hasn't needed any; if a future PR adds one, run `./webodm.sh exec webapp python manage.py migrate` after the swap)
- [ ] Backup the DB if the PR touches models:
  ```bash
  docker exec -t db pg_dumpall -c -U postgres > backup_$(date +%F).sql
  ```
- [ ] Confirm firewall / cloud security group allows 80 + 443 inbound
- [ ] No long-running processing task in a non-resumable stage if you're taking the full-restart path
