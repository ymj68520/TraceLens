"""Entity identity foundation (P5A §9-§12, §16).

Frozen architecture principles implemented here:

    Normalization != Identity Resolution
    Temporal proximity != Causality

A normalizer only produces a canonical representation.  It never asserts that
two occurrences are "the same real thing" — that is the IdentityPolicy's
scoped match-key decision, and even a shared match_key is never an identity
assertion beyond what the policy's auto_link policy sanctions.

Deterministic-first rules (§10):
    SHA256 / SHA1 / MD5  -> strong/global identifier (auto-link allowed)
    path                 -> source-scoped (source_scope qualifier required)
    username             -> host/domain/realm composite qualifier
    IP                   -> same value does NOT mean same person/device
    PID / process image  -> host (+ temporal) scope

There is deliberately NO LLM identity merge and NO ambiguous same-person
reasoning anywhere in this module (P5A §10/§11).  All thresholds and catalog
contents are provisional runtime defaults, subject to P8 calibration.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from enum import Enum
from typing import Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

from ...path_utils import normalize_evidence_path

IDENTITY_POLICY_VERSION = "identity-policy:v1"
ENTITY_TYPE_REGISTRY_VERSION = "entity-type-registry:v1"


class IdentityNormalizationError(ValueError):
    """The raw value cannot be canonically normalized for its entity type."""


class IdentityClass(str, Enum):
    """§12 strong/weak identity ladder. Not all match_keys are equal."""

    STRONG_IDENTIFIER = "strong_identifier"
    SCOPED_IDENTIFIER = "scoped_identifier"
    WEAK_MATCH_KEY = "weak_match_key"


class AutoLinkPolicy(str, Enum):
    """§16: only deterministic-safe identities may auto-link."""

    NEVER = "never"
    ALLOWED = "allowed"


# ---------------------------------------------------------------------------
# normalizers — canonical representation ONLY, never identity assertion
# ---------------------------------------------------------------------------

_HEX_MD5_RE = re.compile(r"[0-9a-f]{32}")
_HEX_SHA1_RE = re.compile(r"[0-9a-f]{40}")
_HEX_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _require_plain(raw: str) -> str:
    if not isinstance(raw, str):
        raise IdentityNormalizationError("entity value must be a string")
    value = raw.strip()
    if not value or any(character.isspace() for character in value):
        raise IdentityNormalizationError(
            f"entity value must be non-empty and space-free: {raw!r}"
        )
    return value


def _normalize_email(raw: str) -> str:
    value = _require_plain(raw)
    if value.count("@") != 1:
        raise IdentityNormalizationError(f"not exactly one '@': {raw!r}")
    local, domain = value.split("@")
    if not local or not domain:
        raise IdentityNormalizationError(f"empty local or domain part: {raw!r}")
    # Local part stays exact; only the domain is case-folded (deterministic
    # canonical representation, no case-based merging of distinct locals).
    return f"{local}@{domain.lower()}"


def _normalize_domain(raw: str) -> str:
    value = _require_plain(raw).lower().rstrip(".")
    if not value or not all(part for part in value.split(".")):
        raise IdentityNormalizationError(f"malformed domain: {raw!r}")
    if "/" in value or "@" in value or not value.isascii():
        raise IdentityNormalizationError(
            f"not a plain ASCII domain (no IDN in P5A): {raw!r}"
        )
    return value


def _normalize_host(raw: str) -> str:
    # A host is a domain or a single label; same ASCII/lowercase rules.
    value = _require_plain(raw).lower().rstrip(".")
    if not value or "/" in value or "@" in value or not value.isascii():
        raise IdentityNormalizationError(f"malformed host: {raw!r}")
    if not all(part for part in value.split(".")):
        raise IdentityNormalizationError(f"malformed host label: {raw!r}")
    return value


def _normalize_url(raw: str) -> str:
    value = _require_plain(raw)
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        raise IdentityNormalizationError(
            f"url requires scheme and host: {raw!r}"
        )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path,
         parts.query, parts.fragment)
    )


def _normalize_ip(raw: str) -> str:
    value = _require_plain(raw)
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise IdentityNormalizationError(f"malformed IP address: {raw!r}") from exc


def _normalize_phone(raw: str) -> str:
    value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        raise IdentityNormalizationError("empty phone value")
    plus = value.startswith("+")
    digits = re.sub(r"[ \-.()\u2013\u2014]", "", value)
    if plus:
        digits = "+" + re.sub(r"\D", "", digits[1:])
        body = digits[1:]
    else:
        digits = re.sub(r"\D", "", digits)
        body = digits
    if not body or not (7 <= len(body) <= 15):
        raise IdentityNormalizationError(
            f"phone must carry 7-15 digits: {raw!r}"
        )
    return digits


_HASH_LENGTHS = {32: ("md5", _HEX_MD5_RE), 40: ("sha1", _HEX_SHA1_RE),
                 64: ("sha256", _HEX_SHA256_RE)}


def _normalize_file_hash(raw: str) -> tuple[str, str]:
    """Return (canonical_hex, hash_name); non-cryptographic lengths fail."""
    value = _require_plain(raw).lower()
    length = len(value)
    if length in _HASH_LENGTHS and _HASH_LENGTHS[length][1].fullmatch(value):
        return value, _HASH_LENGTHS[length][0]
    raise IdentityNormalizationError(
        f"not a md5/sha1/sha256 hex digest: {raw!r}"
    )


def _split_account(raw: str) -> tuple[str, str]:
    """Split user_account into (realm, name); both lowercased canonical form.

    ``DOMAIN\\user``, ``user@realm`` and bare ``user`` are recognized. The
    split is purely syntactic — it never decides that accounts with equal
    names are the same principal (§11)."""
    value = _require_plain(raw).lower()
    if "\\" in value:
        realm, _, name = value.partition("\\")
    elif "@" in value:
        name, _, realm = value.partition("@")
    else:
        realm, name = "", value
    if not name:
        raise IdentityNormalizationError(f"account without name part: {raw!r}")
    return realm, name


def _normalize_process(raw: str) -> str:
    value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        raise IdentityNormalizationError("empty process value")
    basename = re.split(r"[/\\]", value)[-1].lower()
    if not basename:
        raise IdentityNormalizationError(f"malformed process value: {raw!r}")
    return basename


# ---------------------------------------------------------------------------
# versioned entity type registry (§9 — candidate taxonomy, not frozen constants)
# ---------------------------------------------------------------------------


class EntityTypeDefinition(BaseModel):
    """One versioned entity type contract."""

    model_config = ConfigDict(frozen=True)

    entity_type: str
    version: str = "1"
    identity_scope: str
    normalizer_id: str
    match_class: IdentityClass
    auto_link: AutoLinkPolicy = AutoLinkPolicy.NEVER
    required_qualifiers: tuple[str, ...] = ()
    allowed_namespaces: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class EntityTypeRegistry(BaseModel):
    """Versioned registry of the entity types this repo deterministically
    supports. The architecture's candidate taxonomy is deliberately NOT
    frozen; the catalog below is exactly what P5A normalizers support."""

    model_config = ConfigDict(frozen=True)

    types: tuple[EntityTypeDefinition, ...] = ()

    registry_version: str = ENTITY_TYPE_REGISTRY_VERSION

    def get(self, entity_type: str) -> Optional[EntityTypeDefinition]:
        for definition in self.types:
            if definition.entity_type == entity_type:
                return definition
        return None

    def require(self, entity_type: str) -> EntityTypeDefinition:
        definition = self.get(entity_type)
        if definition is None:
            raise IdentityNormalizationError(
                f"unknown entity type {entity_type!r} "
                f"(registry {self.registry_version})"
            )
        return definition

    @property
    def entity_types(self) -> tuple[str, ...]:
        return tuple(definition.entity_type for definition in self.types)

    def catalog_hash(self) -> str:
        payload = {
            "registry_version": self.registry_version,
            "types": [
                self._definition_payload(definition)
                for definition in sorted(self.types, key=lambda d: d.entity_type)
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

    @staticmethod
    def _definition_payload(definition: EntityTypeDefinition) -> dict:
        return {
            "entity_type": definition.entity_type,
            "version": definition.version,
            "identity_scope": definition.identity_scope,
            "normalizer_id": definition.normalizer_id,
            "match_class": definition.match_class.value,
            "auto_link": definition.auto_link.value,
            "required_qualifiers": list(definition.required_qualifiers),
            "allowed_namespaces": list(definition.allowed_namespaces),
            "limitations": list(definition.limitations),
        }

    @classmethod
    def with_defaults(cls) -> "EntityTypeRegistry":
        return cls(types=tuple(_DEFAULT_TYPES))


_DEFAULT_TYPES: tuple[EntityTypeDefinition, ...] = (
    EntityTypeDefinition(
        entity_type="email",
        identity_scope="global",
        normalizer_id="email",
        match_class=IdentityClass.SCOPED_IDENTIFIER,
        allowed_namespaces=("email:global",),
        limitations=("local part kept case-exact",),
    ),
    EntityTypeDefinition(
        entity_type="phone",
        identity_scope="global",
        normalizer_id="phone",
        match_class=IdentityClass.SCOPED_IDENTIFIER,
        allowed_namespaces=("phone:global",),
        limitations=("no country-code inference",),
    ),
    EntityTypeDefinition(
        entity_type="domain",
        identity_scope="global",
        normalizer_id="domain",
        match_class=IdentityClass.SCOPED_IDENTIFIER,
        allowed_namespaces=("domain:global",),
        limitations=("no IDN",),
    ),
    EntityTypeDefinition(
        entity_type="url",
        identity_scope="global",
        normalizer_id="url",
        match_class=IdentityClass.SCOPED_IDENTIFIER,
        allowed_namespaces=("url:global",),
    ),
    EntityTypeDefinition(
        entity_type="ip",
        identity_scope="network",
        normalizer_id="ip",
        match_class=IdentityClass.WEAK_MATCH_KEY,
        allowed_namespaces=("ip:network",),
        limitations=("same IP never implies same person/device",),
    ),
    EntityTypeDefinition(
        entity_type="file_hash",
        identity_scope="global",
        normalizer_id="file_hash",
        match_class=IdentityClass.STRONG_IDENTIFIER,
        auto_link=AutoLinkPolicy.ALLOWED,
        allowed_namespaces=("hash:md5", "hash:sha1", "hash:sha256"),
        limitations=("md5/sha1 collision-prone; treated strong only "
                      "within P5A deterministic linking",),
    ),
    EntityTypeDefinition(
        entity_type="path",
        identity_scope="source_scope",
        normalizer_id="path",
        match_class=IdentityClass.SCOPED_IDENTIFIER,
        required_qualifiers=("source_scope_id",),
        allowed_namespaces=("path:source",),
    ),
    EntityTypeDefinition(
        entity_type="user_account",
        identity_scope="realm_composite",
        normalizer_id="user_account",
        match_class=IdentityClass.WEAK_MATCH_KEY,
        allowed_namespaces=("account:composite", "account:bare"),
        limitations=("same username text never merges without realm",),
    ),
    EntityTypeDefinition(
        entity_type="host",
        identity_scope="source_scope",
        normalizer_id="host",
        match_class=IdentityClass.SCOPED_IDENTIFIER,
        required_qualifiers=("source_scope_id",),
        allowed_namespaces=("host:source",),
    ),
    EntityTypeDefinition(
        entity_type="process",
        identity_scope="host_temporal",
        normalizer_id="process",
        match_class=IdentityClass.WEAK_MATCH_KEY,
        allowed_namespaces=("process:host_temporal", "process:bare"),
        limitations=("PID across host/time is never the same identity",),
    ),
)


# ---------------------------------------------------------------------------
# IdentityPolicy — deterministic resolution over the registry
# ---------------------------------------------------------------------------


class IdentityResolution(BaseModel):
    """Deterministic identity facts for one normalized occurrence value."""

    model_config = ConfigDict(frozen=True)

    entity_type: str
    raw_value: str
    normalized_value: str
    match_key: str
    namespace: str
    identity_class: IdentityClass
    auto_link_allowed: bool
    qualifiers_used: dict


class IdentityPolicy:
    """Deterministic, versioned identity resolution (§10, §53).

    The policy owns match_key construction and the strong/weak ladder. It
    never merges anything by itself; ``auto_link_allowed`` is true only for
    registry-sanctioned strong identifiers (cryptographic hashes)."""

    VERSION = IDENTITY_POLICY_VERSION

    def __init__(self, registry: Optional[EntityTypeRegistry] = None):
        self._registry = registry or EntityTypeRegistry.with_defaults()

    @property
    def registry(self) -> EntityTypeRegistry:
        return self._registry

    @property
    def version(self) -> str:
        return self.VERSION

    def policy_hash(self) -> str:
        """Covers the registry catalog; any policy change moves this hash."""
        return self._registry.catalog_hash()

    def resolve(
        self,
        entity_type: str,
        raw_value: str,
        *,
        qualifiers: Optional[Mapping[str, str]] = None,
    ) -> IdentityResolution:
        definition = self._registry.require(entity_type)
        qualifiers_used: dict = {}
        for name in definition.required_qualifiers:
            value = (qualifiers or {}).get(name)
            if not value:
                raise IdentityNormalizationError(
                    f"entity type {entity_type!r} requires qualifier "
                    f"{name!r}"
                )
            qualifiers_used[name] = str(value)

        if definition.normalizer_id == "email":
            normalized = _normalize_email(raw_value)
            match_key = f"email|{normalized}"
            namespace = "email:global"
        elif definition.normalizer_id == "phone":
            normalized = _normalize_phone(raw_value)
            match_key = f"phone|{normalized}"
            namespace = "phone:global"
        elif definition.normalizer_id == "domain":
            normalized = _normalize_domain(raw_value)
            match_key = f"domain|{normalized}"
            namespace = "domain:global"
        elif definition.normalizer_id == "url":
            normalized = _normalize_url(raw_value)
            match_key = f"url|{normalized}"
            namespace = "url:global"
        elif definition.normalizer_id == "ip":
            normalized = _normalize_ip(raw_value)
            match_key = f"ip|{normalized}"
            namespace = "ip:network"
        elif definition.normalizer_id == "file_hash":
            normalized, hash_name = _normalize_file_hash(raw_value)
            namespace = f"hash:{hash_name}"
            match_key = f"hash|{hash_name}|{normalized}"
        elif definition.normalizer_id == "path":
            normalized = normalize_evidence_path(raw_value)
            if not normalized:
                raise IdentityNormalizationError(
                    f"path normalizes to empty identity: {raw_value!r}"
                )
            scope = qualifiers_used["source_scope_id"]
            match_key = f"path|{scope}|{normalized}"
            namespace = "path:source"
        elif definition.normalizer_id == "host":
            normalized = _normalize_host(raw_value)
            scope = qualifiers_used["source_scope_id"]
            match_key = f"host|{scope}|{normalized}"
            namespace = "host:source"
        elif definition.normalizer_id == "user_account":
            realm, name = _split_account(raw_value)
            realm = realm or (qualifiers or {}).get("realm", "").lower()
            normalized = f"{realm}\\{name}" if realm else name
            if realm:
                match_key = f"account|{realm}/{name}"
                namespace = "account:composite"
                identity_class = IdentityClass.SCOPED_IDENTIFIER
            else:
                match_key = f"account|-/{name}"
                namespace = "account:bare"
                identity_class = IdentityClass.WEAK_MATCH_KEY
        elif definition.normalizer_id == "process":
            normalized = _normalize_process(raw_value)
            host = (qualifiers or {}).get("host", "").lower()
            if host:
                match_key = f"process|host:{host}|{normalized}"
                namespace = "process:host_temporal"
            else:
                match_key = f"process|-|{normalized}"
                namespace = "process:bare"
            identity_class = IdentityClass.WEAK_MATCH_KEY
        else:  # pragma: no cover - registry normalizer ids are closed above
            raise IdentityNormalizationError(
                f"unsupported normalizer {definition.normalizer_id!r}"
            )

        if definition.normalizer_id not in ("user_account", "process"):
            identity_class = definition.match_class
        auto_link_allowed = (
            definition.auto_link is AutoLinkPolicy.ALLOWED
            and identity_class is IdentityClass.STRONG_IDENTIFIER
        )
        return IdentityResolution(
            entity_type=definition.entity_type,
            raw_value=raw_value,
            normalized_value=normalized,
            match_key=match_key,
            namespace=namespace,
            identity_class=identity_class,
            auto_link_allowed=auto_link_allowed,
            qualifiers_used=qualifiers_used,
        )


__all__ = [
    "IDENTITY_POLICY_VERSION",
    "ENTITY_TYPE_REGISTRY_VERSION",
    "AutoLinkPolicy",
    "EntityTypeDefinition",
    "EntityTypeRegistry",
    "IdentityClass",
    "IdentityNormalizationError",
    "IdentityPolicy",
    "IdentityResolution",
]
