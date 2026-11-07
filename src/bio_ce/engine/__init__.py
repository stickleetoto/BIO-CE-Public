# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

"""Engine-neutral client contract (candidate): Community Engine adapter, external engine client, switching.

Nothing in the desktop app, MCP server, or hooks depends on this package yet;
the existing Community behavior is unchanged.
"""

from bio_ce.engine.contract import (
    Capability,
    EngineBackend,
    EngineBinding,
    EngineDescriptor,
    EngineState,
    EngineStatus,
    HostSession,
    MemoryCandidate,
    StaleEngineBinding,
    Support,
    UnsupportedCapability,
    WriteOutcome,
    WriteStatus,
)
from bio_ce.engine.community import COMMUNITY_ENGINE_ID, CommunityEngineAdapter
from bio_ce.engine.external import ExternalEngineAdapter

# The optional Full Core engine is expected to identify itself with this ID; BIO CE contains none of its code.
CORE_ENGINE_ID = "core"
CoreEngineAdapter = ExternalEngineAdapter

__all__ = [
    "COMMUNITY_ENGINE_ID", "CORE_ENGINE_ID", "Capability", "CommunityEngineAdapter", "CoreEngineAdapter",
    "EngineBackend", "EngineBinding", "EngineDescriptor", "EngineState", "EngineStatus", "ExternalEngineAdapter",
    "HostSession", "MemoryCandidate", "StaleEngineBinding", "Support", "UnsupportedCapability", "WriteOutcome",
    "WriteStatus",
]
