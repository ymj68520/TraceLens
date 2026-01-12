#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TESTS_DIR="$ROOT_DIR/tests"
IMAGE="$TESTS_DIR/android_test_gen.img"
SMS_DB="$TESTS_DIR/mmssms_test.db"
CONTACTS_DB="$TESTS_DIR/contacts2_test.db"
CALLLOG_DB="$TESTS_DIR/calllog_test.db"
WA_DB="$TESTS_DIR/msgstore_test.db"
TG_DB="$TESTS_DIR/cache4_test.db"
WC_DB="$TESTS_DIR/EnMicroMsg_test.db"
CHROME_DB="$TESTS_DIR/chrome_history_test.db"
WIFI_CONFIG="$TESTS_DIR/WifiConfigStore.xml"
PACKAGES_XML="$TESTS_DIR/packages.xml"
USAGE_STATS_FILE="$TESTS_DIR/usage_stats_1001"
ASSETS_DIR="$TESTS_DIR/test_assets"
SYSTEM_ASSETS_DIR="$TESTS_DIR/system_assets"

echo "Creating sample Android SQLite databases (SMS, Contacts, CallLog, WhatsApp, Chrome, Telegram, WeChat)..."
command -v sqlite3 >/dev/null 2>&1 || { echo "sqlite3 not found. Please install sqlite3."; exit 1; }

rm -f "$SMS_DB" "$CONTACTS_DB" "$CALLLOG_DB" "$WA_DB" "$CHROME_DB" "$TG_DB" "$WC_DB"

# SMS DB
sqlite3 "$SMS_DB" "CREATE TABLE sms (_id INTEGER PRIMARY KEY, address TEXT, body TEXT, date INTEGER, type INTEGER); INSERT INTO sms (_id, address, body, date, type) VALUES (1, '+1111111111', 'Test SMS message', 1609459200000, 1);"

# Contacts DB
sqlite3 "$CONTACTS_DB" "CREATE TABLE raw_contacts (_id INTEGER PRIMARY KEY, display_name TEXT); CREATE TABLE data (_id INTEGER PRIMARY KEY, raw_contact_id INTEGER, mimetype_id INTEGER, data1 TEXT); CREATE TABLE mimetypes (_id INTEGER PRIMARY KEY, mimetype TEXT);"
sqlite3 "$CONTACTS_DB" "INSERT INTO mimetypes (_id, mimetype) VALUES (1, 'vnd.android.cursor.item/phone_v2');"
sqlite3 "$CONTACTS_DB" "INSERT INTO raw_contacts (_id, display_name) VALUES (1, 'John Doe');"
sqlite3 "$CONTACTS_DB" "INSERT INTO data (raw_contact_id, mimetype_id, data1) VALUES (1, 1, '+1234567890');"

# CallLog DB
sqlite3 "$CALLLOG_DB" "CREATE TABLE calls (_id INTEGER PRIMARY KEY, number TEXT, date INTEGER, duration INTEGER, type INTEGER); INSERT INTO calls (_id, number, date, duration, type) VALUES (1, '+9876543210', 1609462800000, 60, 1);"

# WhatsApp DB
sqlite3 "$WA_DB" "CREATE TABLE messages (_id INTEGER PRIMARY KEY, key_remote_jid TEXT, data TEXT, timestamp INTEGER); INSERT INTO messages (_id, key_remote_jid, data, timestamp) VALUES (1, '12345-67890@g.us', 'Hello from WhatsApp', 1609459201000);"

# Telegram DB (Simplified Simulation)
sqlite3 "$TG_DB" "CREATE TABLE messages (_id INTEGER PRIMARY KEY, uid INTEGER, data TEXT, date INTEGER); INSERT INTO messages (_id, uid, data, date) VALUES (1, 1001, 'Hello from Telegram', 1609459202000);"

# WeChat DB (Simplified Simulation - normally encrypted)
sqlite3 "$WC_DB" "CREATE TABLE message (msgId INTEGER PRIMARY KEY, content TEXT, createTime INTEGER, talker TEXT); INSERT INTO message (msgId, content, createTime, talker) VALUES (1, 'Hello from WeChat', 1609459203000, 'wxid_123456');"

# Chrome History DB
sqlite3 "$CHROME_DB" "CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER, last_visit_time INTEGER); INSERT INTO urls (url, title, visit_count, last_visit_time) VALUES ('https://www.google.com', 'Google', 10, 13254000000000000);"

echo "Creating XML artifacts..."
# Wifi Config
cat > "$WIFI_CONFIG" <<XML
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<WifiConfigStoreData>
<NetworkList>
<Network>
<WifiConfiguration>
<string name="SSID">&quot;MyTestWifi&quot;</string>
<string name="PreSharedKey">&quot;secretpassword&quot;</string>
<string name="KeyMgmt">WPA_PSK</string>
</WifiConfiguration>
</Network>
</NetworkList>
</WifiConfigStoreData>
XML

# Packages XML
cat > "$PACKAGES_XML" <<XML
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<packages>
<package name="com.example.app" codePath="/data/app/com.example.app-1" nativeLibraryPath="/data/app/com.example.app-1/lib" publicFlags="0" privateFlags="0" ft="1609459200000" it="1609459200000" ut="1609459200000" version="1" userId="10000" installer="com.android.vending">
<sigs count="1">
<cert index="0" />
</sigs>
</package>
</packages>
XML

# Usage Stats XML
cat > "$USAGE_STATS_FILE" <<XML
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<usagestats version="1" endTime="1609459200000">
    <packages>
        <package name="com.whatsapp" timeActive="5000" lastTimeActive="1609459100000" />
        <package name="com.android.chrome" timeActive="120000" lastTimeActive="1609459000000" />
        <package name="com.example.app" timeActive="300" lastTimeActive="1609458000000" />
    </packages>
</usagestats>
XML

echo "Creating ext4 image file: $IMAGE (128MB)"
rm -f "$IMAGE"
fallocate -l 128M "$IMAGE"
command -v mkfs.ext4 >/dev/null 2>&1 || { echo "mkfs.ext4 not found. Please install e2fsprogs or mkfs tools."; exit 1; }
mkfs.ext4 -F -q "$IMAGE"

echo "Preparing additional test assets in: $ASSETS_DIR"
rm -rf "$ASSETS_DIR"
mkdir -p "$ASSETS_DIR"

# Create a variety of sample files to populate the image
echo "Sample text file" > "$ASSETS_DIR/sample.txt"
cat > "$ASSETS_DIR/sample.json" <<JSON
{"user":"alice","id":42,"active":true}
JSON
cat > "$ASSETS_DIR/sample.csv" <<CSV
id,name,score
1,Alice,95
2,Bob,88
CSV
echo "Hidden secret" > "$ASSETS_DIR/.hiddenfile"

# small PNG (1x1 transparent) base64
base64 -d > "$ASSETS_DIR/sample.png" <<'PNGBASE64'
iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=
PNGBASE64

# small JPEG (minimal) - use a tiny binary blob to represent an image
printf '%s' "\xFF\xD8\xFF\xD9" > "$ASSETS_DIR/sample.jpg"

# minimal PDF file (very small but valid header + trailer)
cat > "$ASSETS_DIR/sample.pdf" <<'PDF'
%PDF-1.1
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT /F1 24 Tf 50 100 Td (Hello) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000010 00000 n 
0000000060 00000 n 
0000000110 00000 n 
0000000200 00000 n 
trailer << /Root 1 0 R >>
startxref
300
%%EOF
PDF

# dummy apk file
dd if=/dev/urandom of="$ASSETS_DIR/sample.apk" bs=1 count=1024 2>/dev/null || true

# small executable script
cat > "$ASSETS_DIR/runme.sh" <<'SH'
#!/usr/bin/env bash
echo "Hello from test executable"
SH
chmod +x "$ASSETS_DIR/runme.sh"

# small log and config
echo "2025-01-01 00:00:00 App started" > "$ASSETS_DIR/app.log"
cat > "$ASSETS_DIR/config.ini" <<INI
[main]
theme=dark
version=1.2.3
INI

# create a modest binary file to simulate media / large file
dd if=/dev/urandom of="$ASSETS_DIR/large.bin" bs=1M count=4 2>/dev/null || head -c $((4*1024*1024)) < /dev/urandom > "$ASSETS_DIR/large.bin" 2>/dev/null || true

echo "Created $(ls -1 "$ASSETS_DIR" | wc -l) test assets"

# Create system directory assets
echo "Creating system directory assets..."
rm -rf "$SYSTEM_ASSETS_DIR"
mkdir -p "$SYSTEM_ASSETS_DIR/app"
mkdir -p "$SYSTEM_ASSETS_DIR/priv-app"
mkdir -p "$SYSTEM_ASSETS_DIR/framework"

# Create build.prop
cat > "$SYSTEM_ASSETS_DIR/build.prop" <<BUILDPROP
# begin build properties
# autogenerated by buildinfo.sh
ro.build.id=TP1A.220624.014
ro.build.display.id=TP1A.220624.014
ro.build.version.incremental=8650216
ro.build.version.sdk=33
ro.build.version.preview_sdk=0
ro.build.version.codename=REL
ro.build.version.all_codenames=REL
ro.build.version.release=13
ro.build.version.release_or_codename=13
ro.build.version.security_patch=2022-08-05
ro.build.version.base_os=
ro.build.version.min_supported_target_sdk=23
ro.build.date=Wed Aug 10 00:00:00 UTC 2022
ro.build.date.utc=1660089600
ro.build.type=user
ro.build.user=android-build
ro.build.host=abfarm000
ro.build.tags=release-keys
ro.build.flavor=generic_x86_64-user
ro.product.model=Android SDK built for x86_64
ro.product.brand=generic
ro.product.name=generic_x86_64
ro.product.device=generic_x86_64
ro.product.board=
ro.product.cpu.abi=x86_64
ro.product.cpu.abilist=x86_64,x86
ro.product.cpu.abilist32=x86
ro.product.cpu.abilist64=x86_64
ro.product.manufacturer=Google
ro.product.locale=en-US
ro.product.first_api_level=23
ro.board.platform=generic_x86_64
ro.build.product=generic_x86_64
ro.build.description=generic_x86_64-user 13 TP1A.220624.014 8650216 release-keys
ro.build.fingerprint=generic/generic_x86_64/generic_x86_64:13/TP1A.220624.014/8650216:user/release-keys
ro.build.characteristics=default
# end build properties
BUILDPROP

# Create sample system APK files
echo "Sample System App APK content" > "$SYSTEM_ASSETS_DIR/SystemUI.apk"
echo "Sample Privileged App APK content" > "$SYSTEM_ASSETS_DIR/Settings.apk"

# Create framework files
echo "Sample framework JAR content" > "$SYSTEM_ASSETS_DIR/framework.jar"
echo "Sample framework DEX content" > "$SYSTEM_ASSETS_DIR/framework.dex"
echo "Sample framework SO content" > "$SYSTEM_ASSETS_DIR/framework.so"

echo "System assets created"

echo "Writing example files and DBs into image using debugfs (if available), otherwise try mount fallback when running as root..."
if command -v debugfs >/dev/null 2>&1; then
    # Use debugfs to create directories and write DBs and assets
    debugfs -w "$IMAGE" <<EOF
mkdir /data
mkdir /data/data
mkdir /data/data/com.android.providers.telephony
mkdir /data/data/com.android.providers.telephony/databases
write "$SMS_DB" /data/data/com.android.providers.telephony/databases/mmssms.db
mkdir /data/data/com.android.providers.contacts
mkdir /data/data/com.android.providers.contacts/databases
write "$CONTACTS_DB" /data/data/com.android.providers.contacts/databases/contacts2.db
write "$CALLLOG_DB" /data/data/com.android.providers.contacts/databases/calllog.db
mkdir /data/data/com.whatsapp
mkdir /data/data/com.whatsapp/databases
write "$WA_DB" /data/data/com.whatsapp/databases/msgstore.db

mkdir /data/data/org.telegram.messenger
mkdir /data/data/org.telegram.messenger/files
write "$TG_DB" /data/data/org.telegram.messenger/files/cache4.db

mkdir /data/data/com.tencent.mm
mkdir /data/data/com.tencent.mm/MicroMsg
mkdir /data/data/com.tencent.mm/MicroMsg/testuser
write "$WC_DB" /data/data/com.tencent.mm/MicroMsg/testuser/EnMicroMsg.db

mkdir /data/data/com.android.chrome
mkdir /data/data/com.android.chrome/app_chrome
mkdir /data/data/com.android.chrome/app_chrome/Default
write "$CHROME_DB" /data/data/com.android.chrome/app_chrome/Default/History

# Wifi Config
mkdir /data/misc
mkdir /data/misc/wifi
write "$WIFI_CONFIG" /data/misc/wifi/WifiConfigStore.xml

# Packages XML
mkdir /data/system
write "$PACKAGES_XML" /data/system/packages.xml

# Usage Stats
mkdir /data/system/usagestats
mkdir /data/system/usagestats/daily
write "$USAGE_STATS_FILE" /data/system/usagestats/daily/1001

# create typical sdcard and app paths
mkdir /sdcard
mkdir /sdcard/DCIM
mkdir /sdcard/DCIM/Camera
write "$ASSETS_DIR/sample.jpg" /sdcard/DCIM/Camera/sample.jpg
mkdir /sdcard/Download
write "$ASSETS_DIR/sample.pdf" /sdcard/Download/sample.pdf
write "$ASSETS_DIR/sample.png" /sdcard/Download/sample.png

# create system directory
mkdir /system
mkdir /system/app
mkdir /system/priv-app
mkdir /system/framework
write "$SYSTEM_ASSETS_DIR/build.prop" /system/build.prop
write "$SYSTEM_ASSETS_DIR/SystemUI.apk" /system/app/SystemUI.apk
write "$SYSTEM_ASSETS_DIR/Settings.apk" /system/priv-app/Settings.apk
write "$SYSTEM_ASSETS_DIR/framework.jar" /system/framework/framework.jar
write "$SYSTEM_ASSETS_DIR/framework.dex" /system/framework/framework.dex
write "$SYSTEM_ASSETS_DIR/framework.so" /system/framework/framework.so

mkdir /data/media
mkdir /data/media/0
mkdir /data/media/0/Download
write "$ASSETS_DIR/sample.apk" /data/media/0/Download/sample.apk

mkdir /data/data/com.example.app
mkdir /data/data/com.example.app/files
write "$ASSETS_DIR/sample.json" /data/data/com.example.app/files/data.json
write "$ASSETS_DIR/config.ini" /data/data/com.example.app/files/config.ini

mkdir /etc
write "$ASSETS_DIR/config.ini" /etc/config.ini

mkdir /var
mkdir /var/log
write "$ASSETS_DIR/app.log" /var/log/app.log

write "$ASSETS_DIR/.hiddenfile" /root/.hiddenfile

write "$ASSETS_DIR/large.bin" /mnt/sdcard/large.bin

# add executable and set its mode
write "$ASSETS_DIR/runme.sh" /data/local/tmp/runme.sh
chmod 0755 /data/local/tmp/runme.sh
debugfs:  quit
EOF
sync
    echo "Files written to $IMAGE using debugfs"
else
    echo "debugfs not found."
    # If running as root try to mount and copy files (preserve permissions)
    if [ "$(id -u)" -eq 0 ] && command -v losetup >/dev/null 2>&1 && command -v mount >/dev/null 2>&1; then
        echo "Running as root: attaching loop device and mounting image to copy files..."
        LOOP=$(losetup -f --show "$IMAGE")
        mkdir -p /mnt/android_img
        mount "$LOOP" /mnt/android_img
        # create dirs and copy
        mkdir -p /mnt/android_img/data/data/com.android.providers.telephony/databases
        cp "$SMS_DB" /mnt/android_img/data/data/com.android.providers.telephony/databases/mmssms.db
        
        mkdir -p /mnt/android_img/data/data/com.android.providers.contacts/databases
        cp "$CONTACTS_DB" /mnt/android_img/data/data/com.android.providers.contacts/databases/contacts2.db
        cp "$CALLLOG_DB" /mnt/android_img/data/data/com.android.providers.contacts/databases/calllog.db
        
        mkdir -p /mnt/android_img/data/data/com.whatsapp/databases
        cp "$WA_DB" /mnt/android_img/data/data/com.whatsapp/databases/msgstore.db
        
        mkdir -p /mnt/android_img/data/data/org.telegram.messenger/files
        cp "$TG_DB" /mnt/android_img/data/data/org.telegram.messenger/files/cache4.db
        
        mkdir -p /mnt/android_img/data/data/com.tencent.mm/MicroMsg/testuser
        cp "$WC_DB" /mnt/android_img/data/data/com.tencent.mm/MicroMsg/testuser/EnMicroMsg.db
        
        mkdir -p /mnt/android_img/data/data/com.android.chrome/app_chrome/Default
        cp "$CHROME_DB" /mnt/android_img/data/data/com.android.chrome/app_chrome/Default/History
        
        mkdir -p /mnt/android_img/data/misc/wifi
        cp "$WIFI_CONFIG" /mnt/android_img/data/misc/wifi/WifiConfigStore.xml
        
        mkdir -p /mnt/android_img/data/system
        cp "$PACKAGES_XML" /mnt/android_img/data/system/packages.xml
        
        mkdir -p /mnt/android_img/data/system/usagestats/daily
        cp "$USAGE_STATS_FILE" /mnt/android_img/data/system/usagestats/daily/1001

        mkdir -p /mnt/android_img/sdcard/DCIM/Camera
        cp "$ASSETS_DIR/sample.jpg" /mnt/android_img/sdcard/DCIM/Camera/sample.jpg
        mkdir -p /mnt/android_img/sdcard/Download
        cp "$ASSETS_DIR/sample.pdf" /mnt/android_img/sdcard/Download/sample.pdf

        mkdir -p /mnt/android_img/data/media/0/Download
        cp "$ASSETS_DIR/sample.apk" /mnt/android_img/data/media/0/Download/sample.apk

        mkdir -p /mnt/android_img/data/data/com.example.app/files
        cp "$ASSETS_DIR/sample.json" /mnt/android_img/data/data/com.example.app/files/data.json

        mkdir -p /mnt/android_img/var/log
        cp "$ASSETS_DIR/app.log" /mnt/android_img/var/log/app.log

        cp "$ASSETS_DIR/large.bin" /mnt/android_img/mnt/sdcard/large.bin
        cp "$ASSETS_DIR/runme.sh" /mnt/android_img/data/local/tmp/runme.sh
        chmod 0755 /mnt/android_img/data/local/tmp/runme.sh || true

        sync
        umount /mnt/android_img
        losetup -d "$LOOP"
        rmdir /mnt/android_img
        echo "Files copied into $IMAGE via loop mount"
    else
        echo "If you have root, the script can mount the image and copy assets for you. Example (requires sudo):"
        echo "  sudo losetup -f --show $IMAGE && sudo mount /dev/loopX /mnt && sudo cp -a $ASSETS_DIR/. /mnt/ && sudo umount /mnt && sudo losetup -d /dev/loopX"
        echo "Otherwise install debugfs (part of e2fsprogs) to write files without root."
    fi
fi

echo "Image creation complete: $IMAGE"
