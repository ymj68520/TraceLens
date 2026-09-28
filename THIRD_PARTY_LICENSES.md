# Third-party components added for Android containers and filesystem images

This project does not vendor an archive executable or a proprietary SDK. The
following system library is a required build/runtime dependency of the
TAR/7z/Android-Backup adapters:

| Component | Version verified on WSL | License / upstream notice | Use |
| --- | --- | --- | --- |
| libarchive | 3.6.0 (`libarchive-dev` on Ubuntu 22.04) | [Upstream COPYING](https://github.com/libarchive/libarchive/blob/master/COPYING): BSD-style redistribution terms for the distribution, with file-specific 3-clause, public-domain, and alternative-license exceptions listed there. Preserve the notice when redistributing binaries. | Read TAR (including gzip/xz/GNU/PAX) and 7z members on demand; read the validated Android Backup TAR stream. |
| PyCA cryptography | 50.0.1 verified locally; `>=42,<53` required by Python HTTP service | [Upstream LICENSE](https://github.com/pyca/cryptography/blob/main/LICENSE): Apache-2.0 OR BSD-3-Clause | In-memory password-based Android Backup preflight; no executable or model is vendored. |
| qnxprobe | 1.34, commit `fc74ca829c2773879243b326f2262c29f462df3a`; `qnxprobe.py` SHA-256 `ab0f681313bc305f3662d4421199f45da357da3becf90b28696a158fbaae2710` | [Upstream MIT LICENSE](https://github.com/abrignoni/qnxprobe/blob/fc74ca829c2773879243b326f2262c29f462df3a/LICENSE) | Read-only F2FS raw/E01 traversal and exact inode reads. Installed outside tracked source by `scripts/install_android_image_reader.sh`; runtime checks pinned bytes. |
| ewfprobe | bundled with the same qnxprobe commit; `ewfprobe.py` SHA-256 `304616fcdd362339c6890a100eeaba824822f518a09831eb50ed75692f3e52b8` | [Upstream MIT LICENSE](https://github.com/abrignoni/qnxprobe/blob/fc74ca829c2773879243b326f2262c29f462df3a/LICENSE-ewfprobe) | Exposes read-only EWF logical block view to F2FS reader; no full-disk export. |
| AOSP libsparse `simg2img` / `img2simg` | Ubuntu `android-sdk-libsparse-utils` **`1:10.0.0+r36-9`**; verified `/usr/bin/simg2img` SHA-256 `ce77e6e736c3ac65b4f7457ac3d760154c1017762f73bc72f00c5a77dfce09f5` | [AOSP libsparse source](https://android.googlesource.com/platform/system/core/+/refs/tags/android-10.0.0_r36/libsparse/) and file headers: Apache-2.0; [Ubuntu source package](https://packages.ubuntu.com/jammy/android-sdk-libsparse-utils) `android-platform-system-core` | Decode *validated* Android sparse images in an evidence-disjoint Task work directory; `img2simg` is used only by synthetic tests. |
| AOSP `liblp` | `android-10.0.0_r36`, core commit `204bd34e58de124ead5a1e65b852608620077b84` | [AOSP `fs_mgr/liblp`](https://android.googlesource.com/platform/system/core/+/204bd34e58de124ead5a1e65b852608620077b84/fs_mgr/liblp/): Apache-2.0 source headers | Validate LP geometry, metadata, checksums and tables; linked into the repo-native read-only JSON inventory CLI. |
| AOSP `lpmake` / `lpunpack` | `android-10.0.0_r36`, extras commit `ef17b323e8be065ed9fbcd1ea863d72e63488fc0` | [AOSP partition tools](https://android.googlesource.com/platform/system/extras/+/ef17b323e8be065ed9fbcd1ea863d72e63488fc0/partition_tools/): Apache-2.0 source headers | `lpunpack` selectively exports only named system logical partitions; `lpmake` generates synthetic test fixtures. No unknown prebuilt binary is downloaded. |
| AOSP Linux host support libraries | Ubuntu `android-libbase-dev`, `android-liblog-dev`, `android-libsparse-dev`, `android-libcutils-dev`, `android-libcrypto-utils-dev` each `1:10.0.0+r36-9`; `android-libext4-utils-dev` `10.0.0+r36+ds-2` | AOSP `platform/system/core` Apache-2.0 source notices and Ubuntu package copyright files | Required to build pinned `liblp`/`lpunpack` locally with `scripts/install_android_container_tools.sh`. |

Existing project dependencies OpenSSL and zlib are reused for Android Backup
AES/PBKDF2 and zlib decompression. Their licenses and build linkage are
unchanged. The Android Backup stream header and encryption layout were checked
against [AOSP's backup writer](https://android.googlesource.com/platform/frameworks/base/+/3682f501fb72/services/backup/java/com/android/server/backup/fullbackup/PerformAdbBackupTask.java)
and [PasswordUtils](https://android.googlesource.com/platform/frameworks/base/+/28fe597aaf0395ad423868ad75d8ea502d121608/services/backup/java/com/android/server/backup/utils/PasswordUtils.java), both Apache-2.0 source references; no AOSP binary or copied implementation is vendored.

`setup.sh` installs `libarchive-dev`; CMake requires its pkg-config metadata and
fails configuration when it is absent. For another platform, provide a
compatible open-source libarchive build and its license notice before enabling
these adapters.

The sparse/super toolchain is reproducibly built with
`scripts/install_android_container_tools.sh`. Runtime checks the installed
package version, pinned source commits and audited binary SHA-256 values.
Only the source file `scripts/aosp_lp_inventory.cpp` is native TraceLens code;
it calls AOSP liblp rather than reimplementing LP parsing or extent copying.
