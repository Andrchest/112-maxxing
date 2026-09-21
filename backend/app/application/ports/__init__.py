"""Application-layer ports — `typing.Protocol` declarations only (D2).

Every technology-facing capability a use case needs is declared here and implemented in
`app.infrastructure`. Nothing in this package may import sqlalchemy, redis, asyncpg or any other
vendor SDK; `backend/tools/check_imports.py` enforces it.
"""

from __future__ import annotations

from app.application.ports.call_state_cache import CallStateCache
from app.application.ports.call_transport_status import CallTransportStatus
from app.application.ports.caller_belief_repository import CallerBeliefRepository
from app.application.ports.clock import Clock
from app.application.ports.event_publisher import EventEnvelope, EventPublisher, envelope_of
from app.application.ports.event_store import EventStore
from app.application.ports.handoff_repository import HandoffRepository
from app.application.ports.health_probe import ComponentReading, HealthProbe
from app.application.ports.id_generator import IdGenerator
from app.application.ports.inference_readiness import InferenceReadiness
from app.application.ports.llm import (
    ChatMessage,
    JsonSchemaSpec,
    LLMClient,
    LlmCompletion,
    LlmStreamDelta,
    LlmTimeoutError,
    LlmUnavailableError,
    LlmUsage,
)
from app.application.ports.operator_card_repository import OperatorCardRepository
from app.application.ports.password_hasher import PasswordHasher
from app.application.ports.scenario_repository import (
    ScenarioRepository,
    StoredScenario,
    StoredScenarioListing,
    StoredScenarioVersion,
    StoredScenarioVersionDetail,
)
from app.application.ports.session_repository import (
    SessionRepository,
    StoredParticipant,
    StoredSessionListing,
)
from app.application.ports.token_service import (
    InvalidTokenError,
    IssuedToken,
    TokenClaims,
    TokenService,
)
from app.application.ports.tts import (
    TtsChunk,
    TTSProvider,
    TtsStream,
    TtsTimeoutError,
    TtsUnavailableError,
    TtsVoiceSpec,
)
from app.application.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.application.ports.user_repository import StoredUser, UserRepository, UserRole
from app.application.ports.voice_signal_publisher import CANCEL_REASONS, VoiceSignalPublisher
from app.application.ports.voice_token_service import MintedVoiceToken, VoiceTokenService
from app.application.ports.world_truth_repository import WorldTruthRepository

__all__ = [
    "CANCEL_REASONS",
    "CallStateCache",
    "CallTransportStatus",
    "CallerBeliefRepository",
    "ChatMessage",
    "Clock",
    "ComponentReading",
    "EventEnvelope",
    "EventPublisher",
    "EventStore",
    "HandoffRepository",
    "HealthProbe",
    "IdGenerator",
    "InferenceReadiness",
    "InvalidTokenError",
    "IssuedToken",
    "JsonSchemaSpec",
    "LLMClient",
    "LlmCompletion",
    "LlmStreamDelta",
    "LlmTimeoutError",
    "LlmUnavailableError",
    "LlmUsage",
    "MintedVoiceToken",
    "OperatorCardRepository",
    "PasswordHasher",
    "ScenarioRepository",
    "SessionRepository",
    "StoredParticipant",
    "StoredScenario",
    "StoredScenarioListing",
    "StoredScenarioVersion",
    "StoredScenarioVersionDetail",
    "StoredSessionListing",
    "StoredUser",
    "TTSProvider",
    "TokenClaims",
    "TokenService",
    "TtsChunk",
    "TtsStream",
    "TtsTimeoutError",
    "TtsUnavailableError",
    "TtsVoiceSpec",
    "UnitOfWork",
    "UnitOfWorkFactory",
    "UserRepository",
    "UserRole",
    "VoiceSignalPublisher",
    "VoiceTokenService",
    "WorldTruthRepository",
    "envelope_of",
]
