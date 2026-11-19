# Running the engine and the UI on different machines

The studio is one Python process that serves both `ui/dist` and the API, but
nothing requires them to stay together. The UI is a static bundle and the API
already answers cross-origin requests and gates every `/api/*` route except
`/api/health` behind a token.

**No machine address is compiled into the bundle.** The same `ui/dist` works
against any studio; which one it talks to is decided when the page loads.

## The engine machine (for example, the GX10)

```sh
AWO_TOKEN=<a long secret> .venv/bin/python studio.py 8740 --host 0.0.0.0
```

Binding past loopback without `AWO_TOKEN` is refused: the server generates a
token and prints it instead, so set your own to keep it stable across restarts.
The API can run shell commands — keep it on a trusted network, a VPN, an SSH
tunnel, or behind a TLS reverse proxy. Never on a public IP.

Check it from the laptop before touching the UI:

```sh
curl http://gx10.local:8740/api/health
# {"ok": true, "needs_token": true, ...}
```

If that times out, it is a network or firewall problem, not a UI problem.

## The UI machine (the laptop)

Build once, anywhere — the output has no backend address in it:

```sh
cd ui && npm ci && npm run build      # writes ui/dist
```

Serve `ui/dist` with anything:

```sh
npm run preview                        # vite, 0.0.0.0:8741
# or, with only the dist folder copied over:
cd ui/dist && python3 -m http.server 8741
```

Everything the page needs, fonts included, is inside `ui/dist`. There are no
client-side routes, so no SPA rewrite rule is needed.

## Telling the UI where the engine is

Four ways, first hit wins. All of them are runtime, none is a rebuild.

1. **The connect screen.** Open the UI; if it cannot reach a studio it asks for
   the address and token, tries them, and saves them in the browser. Later
   visits go straight in. The host button in the top right reopens it to switch
   machines.
2. **`localStorage`** — `awo-api` and `awo-token`, which is what that screen
   writes.
3. **`awo-config.json`**, served beside `index.html`:

   ```json
   { "api": "http://gx10.local:8740" }
   ```

   Edit it on the static host — it is read fresh on every load, so no rebuild
   and no browser state. Use this when several people share one UI host.
4. **The page's own origin**, which is the single-machine case: the studio
   serving its own `ui/dist`.

A URL can also carry them for a one-off, and they are saved from there too:

```
http://laptop:8741/?api=http://gx10.local:8740&token=<the token>
```

`http://` is added if you leave the scheme off, and a trailing slash is fine.

## Dev against a remote engine

```sh
cd ui
AWO_API=http://gx10.local:8740 npm run dev     # vite on 8741, proxying /api
```

The proxy keeps dev same-origin: no token in the URL, no CORS involved.

## Checks

- `curl http://gx10.local:8740/api/health` answers from the laptop.
- The UI lists workflows. A connect screen saying "that token was not accepted"
  means the address is right and `AWO_TOKEN` is not.
- "no answer" means the studio is not reachable: wrong host or port, not started
  with `--host 0.0.0.0`, or a firewall in between.
