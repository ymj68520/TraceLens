# Decryption Findings

## Scope

TraceLens now supports optional encrypted-volume handling during normal image analysis. The recovered implementation covers password-based BitLocker, LUKS, and VeraCrypt workflows, plus direct BitLocker AES-XTS-128 decryption with a 32-byte FVEK recovered from memory.

## BitLocker FVEK format and cryptography

Volatility 3 `bitlocker_fvek_scan --dump` emits the key material used here as exactly 32 binary bytes:

- bytes 0-15: AES data key
- bytes 16-31: AES tweak key

The cipher is AES-128-XTS (`EVP_aes_128_xts`). Each 512-byte sector uses the absolute physical sector index within the BitLocker partition as its XTS tweak. A key that decrypts one volume must not be assumed to belong to another volume; verify the result by locating a valid NTFS boot sector and opening the output with a filesystem parser.

The standalone helper `bitlocker_fvek_decrypt.py` supports these coordinate controls:

- `--data-start-sector`: input sector where encrypted data processing begins
- `--sector-base`: physical partition-relative sector represented by input sector zero
- `--max-sectors`: bounded test/decryption length

Auto-detection tests sectors near the start of the input, locates a valid NTFS boot sector, and aligns output sector zero to that boot sector so Sleuth Kit receives a normal raw NTFS volume.

## Image and EWF offsets

Keep these coordinate systems distinct:

1. whole-image/EWF byte offset
2. partition-relative byte offset
3. input-stream sector zero
4. BitLocker partition physical sector index used as the XTS tweak

An EWF segment is not an ordinary raw file. Small requested ranges are exported through `ewfexport` when direct reads fail or are partial. The `-t` argument is a prefix without an extension because `ewfexport` appends `.raw`; passing a target already ending in `.raw` produces an incorrect `.raw.raw` path.

A previously investigated sample exposed the `-FVE-FS-` signature at partition-relative sector 26088, demonstrating that BitLocker metadata must not be assumed to begin at sector 8 (`0x1000`).

## Application integration

Decryption settings flow through both supported entry points:

- CLI: `--decrypt`, `--key-dir`, `--key-password`
- HTTP task creation: `enable_decryption`, `key_dir`, `decrypt_password`

The settings reach `ImageAnalyzer`, which uses `KeyFileLoader` and `DecryptionModule`, then passes successfully decrypted volumes into the existing filesystem walking and extraction paths. The integration preserves multi-partition enumeration and normal raw/EWF analysis behavior.

Password files use the sibling naming convention `<imageBase>.part<N>.key`, with `<imageBase>.key` as the whole-image fallback. Binary 32-byte `.fvek` files are handled separately and validated before direct BitLocker decryption.

## Validation criteria and cautions

A running decryptor is not sufficient evidence of success. Require all of the following where a real encrypted sample is available:

- valid NTFS boot-sector fields and `0x55aa` trailer
- filesystem parser acceptance
- successful directory traversal and real file extraction
- downstream TraceLens analysis of the extracted records

The previously identified candidate 2 key may belong to a different volume (possibly the C: volume rather than the intended D: volume). Wrong key/volume pairing and an incorrect XTS sector basis both produce high-entropy output that can look like an implementation failure.

Do not attempt unrestricted decryption of large evidence images during routine tests. Use `--max-sectors` and a copied test range first.
