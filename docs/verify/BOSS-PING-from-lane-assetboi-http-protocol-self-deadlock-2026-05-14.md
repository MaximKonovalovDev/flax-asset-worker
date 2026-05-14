# BOSS-PING — lane assetboi — HTTP-PING protocol self-deadlock — 2026-05-14

> Filed file-based because HTTP-PING from a lane TO ITS OWN session deadlocks
> (see analysis below). This is a **discovery report**, not a blocker — the
> file-based backup channel works.

## 1. What I tried

Followed `docs/parallel/BOSS-PING-HTTP-protocol.md` exactly:

```pwsh
POST http://127.0.0.1:5000/session/ses_1f992c7b2ffeVx1fE7nOdi0xUC/message
auth: Basic opencode:<pw>
body: {agent:'general', parts:[{type:'text',text:'[PING from lane-assetboi]...'}], model:{providerID:'perplexity-agent',modelID:'anthropic/claude-opus-4-7'}}
```

Two attempts: `Invoke-WebRequest` (PS 5.1) and raw `HttpWebRequest` with
5-second timeout. Both **time out** — no HTTP response, no error code.

Port 5000 IS listening (verified via `Get-NetTCPConnection`). Daemon is
healthy (my own turn is still running).

## 2. Hypothesis

The OpenCode daemon's `POST /session/<id>/message` endpoint **synchronously
waits for the next assistant turn to begin processing the queued message
before returning HTTP 2xx.** This is fine for cross-session pings (sender
session is idle, receiver session can take its turn immediately) — but
**creates self-deadlock when a lane tries to POST to its own session**:

```
[lane-assetboi mid-turn] -> POST /session/.../message
                          ^ waits for turn to end
[daemon] -> can't start new turn while current turn alive
                          ^ deadlock
```

My current turn can only end AFTER the HTTP call returns; the HTTP call can
only return AFTER my current turn ends. Mutex.

## 3. What works regardless

- **File-based PING** (`docs/verify/BOSS-PING-from-lane-*.md`) works fine
  for self-pings; maestro's poll cycle picks it up on next round.
- **HTTP-PING cross-session** (lane-A pinging lane-B's session) should
  work since lane-A is idle when sending.

## 4. Recommendations for the protocol doc

Either:
- **Document the limitation**: "HTTP-PING does not work from a lane to its
  own session; use file-based for self-pings."
- **Make the endpoint async**: daemon should `202 Accepted` the message
  into a queue and return immediately, letting the next-turn dispatcher
  pick it up. Single-line change in the daemon HTTP handler.

If maestro implements the async fix, all lanes get sub-second HTTP-PING
for self-status updates too — much better than the polling cycle.

## 5. What would unblock me

Nothing. The file-based channel is fine for my needs. This is purely a
discovery report so maestro knows the HTTP path has this gotcha.

If you want me to keep trying HTTP-PING for **cross-lane** pings (e.g.
flagging something to lane-flaxcoder if there's a shared concern), I can —
that's the path that doesn't deadlock.

## 6. Continuing work

No pause. Currently on v1.44.1 Archive.org --license filter (just
shipped). Next slice: Unsplash --license filter mirror (s246), then
ship v1.44 wave-complete.

State: 297 commits / 282 tags / 969 tests / 31 consecutive waves / 0
RULE violations.

---
Lane: `assetboi`. Topic: `http-protocol-self-deadlock`. Date: `2026-05-14`.
