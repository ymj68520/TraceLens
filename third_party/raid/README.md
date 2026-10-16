# RAID upstream source bundle

All tracked upstream files (not snippets or binary-only downloads) are stored
under `upstream/`. Each source snapshot includes its original licenses,
copyright notices, tests and `SOURCE.json`: exact commit, archive SHA-256 and
per-file SHA-256. `sources.lock.json` is the authoritative upstream selection.
No `.git` submodule or runtime internet access is required to use these sources.

```sh
python3 scripts/raid_vendor_sources.py verify
# Explicit development action only, if sources have not been obtained:
python3 scripts/raid_vendor_sources.py fetch
# Create the complete, verified source distribution once:
python3 scripts/raid_vendor_sources.py bundle
```

Existing source directories are never overwritten. Modified snapshots fail
verification; upgrades require a newly named snapshot and an explicit review.
Acquiring sources does not enable them as runtime dependencies automatically.

`sources.bundle.tar.gz` includes every upstream file and original notice, even
fuzz seeds and Windows sources ignored by parent/upstream `.gitignore` rules.
Upstream test images (`tests/_data`, `tests/data`) are not part of the checked-in
snapshots: they were Git LFS pointers, unused by the adapter, and omitted from
`SOURCE.json`. The historical bundles still contain the older inventory.
`sources.bundle.sha256` verifies this complete source delivery artifact. Include
the bundle when publishing; don't assume a default `git add` picks every file in
the unpacked source tree. Offline restoration in a fresh checkout is simply
`tar -xzf sources.bundle.tar.gz` from this directory, then run `verify` at the
project root. Restore only into a fresh tree, never over locally modified code.

## Runtime selection

- `dissect.volume`: original AGPL-3.0-or-later source, fixed commit.
- `dissect.cstruct-4.7` and `dissect.util`: Apache-2.0 dependencies.
- `dissect.ntfs` / `dissect.fat`: AGPL-3.0-or-later, readonly validation and file
  read-back of metadata-free candidates. Full pinned sources are local.
- `qnxprobe/ewfprobe.py`: the same pinned MIT EWF reader already used by the
  Android image adapter; full repository included, no automatic segment glob.
- `dissect.cstruct` main snapshot: retained for audit, **not loaded**. It is
  incompatible with volume's `dissect.cstruct>=4,<5` contract.
- `mdadm`: optional standalone read-only `--examine` test oracle. No installation,
  kernel assembly, recovery, service activation or scan of host devices.
- `raid_recovery`: saved for the metadata-free RAID5 follow-up, **not enabled**.
- `nbdkit` / `libnbd`: saved for the virtual C++ integration follow-up, **not
  enabled**. Their active upstreams are GitLab, not the unmaintained GitHub mirrors.

## Licensing and source availability

New RAID adapter files under `raid/`, its CLI and synthetic tests are explicitly
licensed **AGPL-3.0-or-later**, with the full text in `raid/LICENSE`. They are not
relabelled as MIT. The existing TraceLens MIT license remains unchanged.
The MIT source retrieval/build scripts do not change upstream licensing.

Redistribution must include the corresponding pinned source, local adaptations,
build scripts and each original notice. Network deployment of an AGPL-based
component must satisfy its source-availability obligations. Packaging as a
subprocess does not by itself establish an exemption for a combined program.
Do not claim the entire resulting distribution is MIT-only. Resolve the final
combined distribution's license obligations before publishing/releasing it.

The full source is local and suitable for an open-source release; this change
does **not** publish a repository or push to a remote on the user's behalf.

`SOURCE.json` is an acquisition manifest, not an upstream signature. Verification
detects drift against the pinned local inventory; a trusted release must also
freeze this lock and inventories in its reviewed commit.

For the metadata-free milestone use `sources.bundle-v2.tar.gz` and its SHA-256
sidecar: 11 snapshots from 10 repositories, 2880 upstream files. The original
9-snapshot bundle remains untouched as a previous milestone artifact. Generate
new bundles explicitly with `bundle --bundle-name sources.bundle-v2.tar.gz`;
existing artifacts are never overwritten.
