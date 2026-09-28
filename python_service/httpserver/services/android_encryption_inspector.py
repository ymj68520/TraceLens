"""Evidence-based Android at-rest encryption assessment; never decrypts."""

from __future__ import annotations


class AndroidEncryptionInspector:
    F2FS_FBE_FEATURE = 0x1
    EXT4_FBE_INCOMPAT = 0x10000

    @classmethod
    def inspect(cls, volume: dict, *, metadata_fstab: str | None = None) -> dict:
        filesystem = volume.get("kind")
        flags = volume.get("feature_flags")
        encrypted = int(volume.get("encrypted_files") or 0)
        readable = int(volume.get("readable_files") or 0)
        evidence = []
        if filesystem == "f2fs" and isinstance(flags, int):
            if flags & cls.F2FS_FBE_FEATURE:
                evidence.append("F2FS_FEATURE_ENCRYPT")
        elif filesystem == "ext4" and isinstance(flags, int):
            if flags & cls.EXT4_FBE_INCOMPAT:
                evidence.append("EXT4_FEATURE_INCOMPAT_ENCRYPT")
        if encrypted:
            evidence.append(f"encrypted_inode_count={encrypted}")
        # Only an actual readable fstab metadata_encryption setting justifies
        # a metadata-encryption claim. The existence of a metadata partition
        # alone is not enough.
        if metadata_fstab and "metadata_encryption=" in metadata_fstab:
            evidence.append("fstab:metadata_encryption")
        if encrypted and not readable:
            state = "LOCKED"
        elif encrypted and readable:
            state = "PARTIALLY_ACCESSIBLE"
        elif "fstab:metadata_encryption" in evidence:
            state = "METADATA_ENCRYPTION_DETECTED"
        elif any(item.endswith("ENCRYPT") for item in evidence):
            state = "FBE_DETECTED"
        elif isinstance(flags, int) and readable:
            state = "UNENCRYPTED"
            evidence.append("no_filesystem_encryption_feature_and_readable_artifacts")
        else:
            state = "UNKNOWN"
        return {"state": state, "evidence": evidence,
                "confidence_basis": "filesystem feature flags and observed inode readability; "
                                    "fstab only when actually readable"}
