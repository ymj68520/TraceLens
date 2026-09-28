# P8B benchmark mini images

Purpose-built 16MB ext4 images for the frozen B2 calibration cases
(corpus-agent-v0-b2 v3). Each image is reproducible: the dataset files
under `benchmarks/cases/<case_id>/dataset/` are byte-identical to the
files inside the image (verified by debugfs dump + sha256).

- `t2-identity-trap.img` (label trapfs): two unrelated log exports, same
  username `chenwei` on both systems, shared office IP — identity trap.
- `t2-no-evidence.img` (label cleanfs): benign office documents only.
- `t2-temporal-trap.img` (label tempfs): owner chat + recovered
  third-party chat with USDT deposits, time-adjacent — causality trap.

Rebuild procedure (any Linux with mke2fs/debugfs):
  dd if=/dev/zero of=<img> bs=1M count=16
  mke2fs -q -t ext4 -L <label> -I 256 -b 1024 <img>
  debugfs -w -R "mkdir /<dir>" <img>            # where needed
  debugfs -w -R "write <staged-file> /<path>" <img>
Dataset-file identity is enforced by the case manifests, not by image
bytes; the images are inputs to ingestion, never hashed as evidence.
