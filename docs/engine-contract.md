<!-- Copyright 2026 stickleetoto | Apache-2.0 -->
# Engine contract (candidate)

**Status:** contract candidate, protocol version 1. Not yet used by the desktop app, MCP server, or hooks; their
behavior is unchanged. Verified with the Community Engine and synthetic engines only.

BIO CE is moving toward one client (desktop app, MCP server, hooks) that can talk to more than one memory engine:

- the **Community Engine** built into BIO CE (default, always available), and
- an optional engine installed separately that speaks the same public protocol.

BIO CE contains no code of any other engine. Engines keep separate databases; choosing another engine never copies,
merges, or migrates memories.

## Package `bio_ce.engine`

| Module | Purpose |
|---|---|
| `contract.py` | Capabilities, support levels, protocol negotiation, engine-neutral views, typed write outcomes, the `EngineBackend` and `HostSession` protocols |
| `community.py` | `CommunityEngineAdapter`: the existing `DesktopMemoryService`, grant checks, and Auto memory policy behind the contract, without new behavior |
| `external.py` | `ExternalEngineAdapter`: client for an engine reached through an injected transport; nothing is sent until a transport exists |
| `switching.py` | `EngineRouter`: the active engine, binding generations, and the switch state machine |

## Rules

1. **Negotiated, not assumed.** The client offers a capability only if the engine declares it *and* this client
   release has verified it for that engine. The default verification list for an external engine is empty, so every
   capability of a real external engine shows as `unverified` until a release verifies it end to end.
2. **Typed outcomes.** `saved`, `pending_review`, `duplicate`, `rejected`, `conflict`, `not_supported`. Only `saved`
   means a memory was stored. A proposal waiting for review is never shown as a saved memory.
3. **Not routed to an external engine by this client:** direct user edits, review decisions, backup and restore. They
   need that engine's own user authority.
4. **Host evidence is a claim.** A host's `evidence` value is forwarded as `claimed_evidence`; the engine decides.
5. **Engine-scoped IDs.** Every view carries `engine_id`; memory IDs are opaque and never compared across engines.
6. **Fail closed.** Not installed, not running, incompatible, or unauthorized is reported as a status. Nothing falls
   back to another engine.

## Capabilities

| Capability | Community Engine |
|---|---|
| `memory_search`, `memory_get`, `memory_list`, `memory_history` | supported |
| `context_pack` | limited (lexical hook context) |
| `memory_propose` | supported (Auto memory policy) |
| `direct_user_edit`, `review_queue`, `backup_restore`, `host_auth` | supported |

## Switching

```text
ACTIVE(old) -> QUIESCE -> REVOKE_OLD -> NEGOTIATE -> BIND_NEW -> VERIFY -> ACTIVE(new)
                  any failure, or a crash in between  ->  SAFE_DISCONNECTED
```

- QUIESCE raises the binding generation first. Any request made under the old binding is refused afterwards and
  reaches no engine.
- Old host grants must be revoked before anything is bound to the new engine.
- `SAFE_DISCONNECTED` has no active engine. The user recovers by choosing an engine again; there is no automatic
  fallback. A selection file that cannot be read also gives `SAFE_DISCONNECTED`.
- No selection file means the Community Engine, generation 0.

## Not done yet

- The desktop app, MCP server, and hooks still call the Community Engine directly.
- Binding generations are enforced in one process. Separate MCP server and hook processes need the generation stored
  with each connection grant, which changes the control database and needs approval first.
- No engine selection UI.
- The external-engine operation names are a candidate and must be confirmed with the engine owner.
