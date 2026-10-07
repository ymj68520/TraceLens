qnxprobe, built as standalone executables
==========================================

  qnxprobe            the command line tool (qnxprobe.exe on Windows). Open a
                      terminal in this folder and run, for example:
                          qnxprobe --self-test
                          qnxprobe mmcblk0.img
                          qnxprobe --list --depth 3 mmcblk0.img
                          qnxprobe --extract out.zip mmcblk0.img
                          qnxprobe --help
                      On Windows write qnxprobe.exe; on macOS and Linux write
                      ./qnxprobe from this folder.

  qnxprobe_gui        the window: qnxprobe_gui.exe on Windows, the
                      qnxprobe_gui.app bundle on macOS, ./qnxprobe_gui on
                      Linux. Open it, add an image, and press Run report,
                      Extract to zip, or open the Contents tab and press Load
                      contents.

  SHA256SUMS.txt      the hashes of the executables as built. Check them with
                          certutil -hashfile qnxprobe.exe SHA256     (Windows)
                          shasum -a 256 -c SHA256SUMS.txt            (macOS)
                          sha256sum -c SHA256SUMS.txt                (Linux)

Both open the image read-only and never write to it. Neither installs anything
or needs administrator rights. They are built from the same two Python files in
https://github.com/abrignoni/qnxprobe by the repository's own GitHub Actions
workflow, and are not code signed:

  Windows   SmartScreen may ask once before running them. Unzip to a local
            folder rather than running from a network share.
  macOS     Gatekeeper will refuse a downloaded, unsigned app on first open.
            Right-click (Control-click) the app or the qnxprobe binary and
            choose Open, once, or remove the quarantine mark:
                xattr -dr com.apple.quarantine .
  Linux     mark the two files executable if the archive did not keep the bit:
                chmod +x qnxprobe qnxprobe_gui
            The window needs a display; the command line tool does not.

Builds: windows-x64, windows-arm64 (native for Windows on ARM; the x64 build
also runs there through emulation), macos-arm64 (Apple silicon), macos-x64
(Intel), linux-x64, linux-arm64.
