qnxprobe {{VERSION}}: standalone executables of `qnxprobe.py` and `qnxprobe_gui.py`, built by this repository's own GitHub Actions workflow from the tagged commit.

- `qnxprobe-{{VERSION}}-windows-x64.zip` runs on Intel and AMD PCs, and on Windows on ARM through its x64 emulation.
- `qnxprobe-{{VERSION}}-windows-arm64.zip` is native for Windows on ARM.
- `qnxprobe-{{VERSION}}-macos-arm64.zip` for Apple silicon Macs, `qnxprobe-{{VERSION}}-macos-x64.zip` for Intel Macs.
- `qnxprobe-{{VERSION}}-linux-x64.tar.gz` and `qnxprobe-{{VERSION}}-linux-arm64.tar.gz`, built on Ubuntu 22.04 so they run on distributions with a glibc at least that old.

Each archive holds the command line tool, the window (a `.app` bundle on macOS), `README.txt`, `LICENSE` and `SHA256SUMS.txt`. `SHA256SUMS.txt` beside the archives covers the archives themselves. None of the executables is code signed: Windows SmartScreen and macOS Gatekeeper will each ask once, and the README inside says what to do. Unzip to a local folder rather than running from a network share.

The Python files themselves need nothing built: `python3 qnxprobe.py` works on macOS, Linux and Windows with the standard library alone. See the README for what each release of the tool reads.
