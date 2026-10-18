"""P5A §53 IdentityPolicy tests: normalization != identity, strong vs weak
match keys, scoped qualifiers, and deterministic policy hashing."""

import pytest

from httpserver.services.investigation.agent_identity import (
    AutoLinkPolicy,
    EntityTypeDefinition,
    EntityTypeRegistry,
    IdentityClass,
    IdentityNormalizationError,
    IdentityPolicy,
)


def test_same_input_normalizes_deterministically():
    policy = IdentityPolicy()
    first = policy.resolve("domain", "Example.COM.")
    second = policy.resolve("domain", "Example.COM.")
    assert first.normalized_value == "example.com" == second.normalized_value
    assert first.match_key == second.match_key
    assert policy.policy_hash() == IdentityPolicy().policy_hash()


def test_normalization_is_never_identity_merge():
    """Case-folding a username is canonical representation only: the bare
    match_key stays weak and never auto-links, so no identity is asserted."""
    policy = IdentityPolicy()
    assert (
        policy.resolve("user_account", "Alice").normalized_value
        == policy.resolve("user_account", "alice").normalized_value
        == "alice"
    )
    bare = policy.resolve("user_account", "administrator")
    assert bare.identity_class is IdentityClass.WEAK_MATCH_KEY
    assert bare.auto_link_allowed is False
    assert bare.namespace == "account:bare"


def test_strong_identifier_auto_link_allowed():
    policy = IdentityPolicy()
    resolution = policy.resolve("file_hash", "ab" * 32)
    assert resolution.identity_class is IdentityClass.STRONG_IDENTIFIER
    assert resolution.auto_link_allowed is True
    assert resolution.namespace == "hash:sha256"


def test_hash_normalizer_rejects_non_digest_values():
    policy = IdentityPolicy()
    for bad in ("not-a-hash", "12345", "zz" * 32, ""):
        with pytest.raises(IdentityNormalizationError):
            policy.resolve("file_hash", bad)


def test_weak_match_requires_scoped_qualifier():
    policy = IdentityPolicy()
    with pytest.raises(IdentityNormalizationError):
        policy.resolve("path", "C:/Users/x/a.doc")  # missing source_scope
    scoped = policy.resolve(
        "path", "C:/Users/x/a.doc", qualifiers={"source_scope_id": "img-1"}
    )
    assert scoped.match_key == "path|img-1|C:/Users/x/a.doc"
    assert scoped.namespace == "path:source"
    assert scoped.auto_link_allowed is False


def test_different_realm_username_is_never_same_identity():
    policy = IdentityPolicy()
    corp = policy.resolve("user_account", "john", qualifiers={"realm": "CORP"})
    home = policy.resolve("user_account", "john", qualifiers={"realm": "HOME"})
    assert corp.match_key != home.match_key
    assert corp.namespace == "account:composite"
    assert corp.auto_link_allowed is False and home.auto_link_allowed is False


def test_process_pid_across_host_is_never_same_identity():
    policy = IdentityPolicy()
    host_a = policy.resolve("process", "1337", qualifiers={"host": "host-a"})
    host_b = policy.resolve("process", "1337", qualifiers={"host": "host-b"})
    assert host_a.match_key != host_b.match_key
    assert host_a.identity_class is IdentityClass.WEAK_MATCH_KEY
    assert host_a.auto_link_allowed is False


def test_policy_change_moves_policy_hash():
    base = EntityTypeRegistry.with_defaults()
    modified_types = []
    for definition in base.types:
        if definition.entity_type == "ip":
            modified_types.append(
                definition.model_copy(
                    update={"identity_scope": "global",
                            "match_class": IdentityClass.STRONG_IDENTIFIER,
                            "auto_link": AutoLinkPolicy.ALLOWED}
                )
            )
        else:
            modified_types.append(definition)
    changed = IdentityPolicy(EntityTypeRegistry(types=tuple(modified_types)))
    unchanged = IdentityPolicy()
    assert changed.policy_hash() != unchanged.policy_hash()
    # the changed policy now (wrongly) allows IP auto-link — proving the
    # hash tracks policy content, not just the version constant
    assert changed.resolve("ip", "10.0.0.1").auto_link_allowed is True
    assert unchanged.resolve("ip", "10.0.0.1").auto_link_allowed is False


def test_registry_requires_known_type_and_qualifiers():
    policy = IdentityPolicy()
    with pytest.raises(IdentityNormalizationError):
        policy.resolve("cryptocurrency_wallet", "bc1qxyz")
    with pytest.raises(IdentityNormalizationError):
        policy.resolve("host", "srv01")  # missing source_scope qualifier


def test_normalizer_canonical_forms():
    policy = IdentityPolicy()
    assert policy.resolve("email", "User@Example.COM").normalized_value == (
        "User@example.com"
    )
    assert policy.resolve("ip", "0000:0000:0000:0000:0000:0000:0000:0001"
                         ).normalized_value == "::1"
    assert policy.resolve("phone", "+1 (555) 010-2030").normalized_value == (
        "+15550102030"
    )
    assert policy.resolve(
        "url", "HTTP://Example.COM/Path?q=1"
    ).normalized_value == "http://example.com/Path?q=1"
    md5 = policy.resolve("file_hash", "A" * 32)
    assert md5.namespace == "hash:md5"
    assert md5.auto_link_allowed is True
