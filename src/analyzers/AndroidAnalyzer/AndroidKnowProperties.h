#pragma once
#include <map>
#include <string>
// Build Property Categories and Analysis Data
struct PropertyDefinition {
    std::string category;
    std::string description;
    std::string securityImplication;
};

// Known build properties database
static const std::map<std::string, PropertyDefinition> KNOWN_PROPERTIES = {
    // Device Information
    {"ro.product.manufacturer", {"Device", "Device manufacturer", "Low"}},
    {"ro.product.brand", {"Device", "Product brand", "Low"}},
    {"ro.product.model", {"Device", "Product model", "Low"}},
    {"ro.product.device", {"Device", "Product device name", "Low"}},
    {"ro.product.name", {"Device", "Product name", "Low"}},
    {"ro.product.mod_device", {"Device", "Mod device identifier", "Low"}},
    {"ro.miui.cust_device", {"Device", "MIUI custom device", "Low"}},

    // Build Information
    {"ro.build.id", {"Build", "Build identifier", "Low"}},
    {"ro.build.version.release", {"Build", "Android version", "Low"}},
    {"ro.build.version.sdk", {"Build", "Android SDK version", "Low"}},
    {"ro.build.version.security_patch", {"Build", "Security patch level", "High"}},
    {"ro.build.date", {"Build", "Build date", "Medium"}},
    {"ro.build.date.utc", {"Build", "Build date (UTC)", "Medium"}},
    {"ro.build.type", {"Build", "Build type (user/debug)", "High"}},
    {"ro.build.tags", {"Build", "Build tags", "Medium"}},
    {"ro.build.fingerprint", {"Build", "Build fingerprint for verification", "High"}},
    {"ro.build.version.incremental", {"Build", "Incremental build number", "Low"}},
    {"ro.build.keys", {"Build", "Release keys", "High"}},

    // Security Configuration
    {"ro.secure", {"Security", "Secure mode enabled", "Critical"}},
    {"ro.adb.secure", {"Security", "ADB secure mode", "Critical"}},
    {"ro.allow.mock.location", {"Security", "Mock location permission", "High"}},
    {"ro.debuggable", {"Security", "Debug mode enabled", "Critical"}},
    {"ro.config.vold_postfs_data_defer", {"Security", "Volume manager defer", "Medium"}},
    {"security.perf_harden", {"Security", "Performance hardening", "Medium"}},
    {"ro.secureboot.devicelock", {"Security", "Secure boot device lock", "High"}},

    // System Configuration
    {"ro.sf.lcd_density", {"System", "Screen density", "Low"}},
    {"ro.product.cpu.abi", {"System", "Primary CPU ABI", "Low"}},
    {"ro.product.cpu.abilist", {"System", "CPU ABI list", "Low"}},
    {"ro.product.cpu.abilist32", {"System", "32-bit CPU ABI list", "Low"}},
    {"ro.product.cpu.abilist64", {"System", "64-bit CPU ABI list", "Low"}},
    {"ro.opengles.version", {"System", "OpenGL version", "Low"}},
    {"ro.product.locale", {"System", "Default locale", "Medium"}},
    {"persist.sys.timezone", {"System", "System timezone", "Medium"}},

    // Telephony
    {"ro.telephony.default_network", {"Telephony", "Default network type", "Medium"}},
    {"ro.vendor.radio.features_common", {"Telephony", "Radio features", "Medium"}},
    {"ril.subscription.types", {"Telephony", "Subscription types", "Low"}},
    {"telephony.lteOnCdmaDevice", {"Telephony", "LTE on CDMA support", "Low"}},

    // MIUI/Xiaomi Specific
    {"ro.miui.ui.version.code", {"MIUI", "MIUI version code", "Low"}},
    {"ro.miui.ui.version.name", {"MIUI", "MIUI version name", "Low"}},
    {"ro.miui.restrict_imei", {"MIUI", "IMEI restriction", "High"}},
    {"ro.miui.has_cust_partition", {"MIUI", "Custom partition present", "Medium"}},
    {"ro.miui.has_security_keyboard", {"MIUI", "Security keyboard present", "Medium"}},
    {"ro.miui.support_miui_ime_bottom", {"MIUI", "Bottom IME support", "Low"}},
    {"ro.miui.ui.fonttype", {"MIUI", "MIUI font type", "Low"}},
    {"ro.miui.remove_uri_80_flag", {"MIUI", "URI 80 flag removal", "Medium"}},
    {"ro.mi.development", {"MIUI", "Development mode", "High"}},
    {"ro.rom.zone", {"MIUI", "ROM zone (regional)", "Medium"}},

    // Network and Connectivity
    {"ro.hardware.wlan.vendor", {"Network", "WiFi vendor", "Low"}},
    {"ro.hardware.wlan.chip", {"Network", "WiFi chip", "Low"}},
    {"ro.hardware.wlan.mimo", {"Network", "WiFi MIMO support", "Low"}},
    {"ro.hardware.wlan.dbs", {"Network", "WiFi dual band simultaneous", "Low"}},
    {"ro.config.gnss.support", {"Network", "GPS support", "Low"}},
    {"ro.nfc.port", {"Network", "NFC port", "Low"}},
    {"ro.bluetooth.library_name", {"Network", "Bluetooth library", "Low"}},

    // Media and Graphics
    {"media.stagefright.enable-player", {"Media", "Media player enable", "Low"}},
    {"media.stagefright.enable-aac", {"Media", "AAC support", "Low"}},
    {"media.stagefright.enable-qcp", {"Media", "QCP support", "Low"}},
    {"qcom.hw.aac.encoder", {"Media", "AAC encoder", "Low"}},
    {"ro.surface_flinger.supports_background_blur", {"Graphics", "Background blur support", "Low"}},
    {"ro.miui.has_real_blur", {"Graphics", "Real blur support", "Low"}},
    {"ro.launcher.blur.appLaunch", {"Graphics", "Launcher blur on app launch", "Low"}},

    // Memory and Performance
    {"dalvik.vm.heapsize", {"Performance", "Dalvik heap size", "Medium"}},
    {"dalvik.vm.dexopt.secondary", {"Performance", "Secondary DEX optimization", "Medium"}},
    {"dalvik.vm.usejit", {"Performance", "JIT compilation", "Medium"}},
    {"dalvik.vm.usejitprofiles", {"Performance", "JIT profiles", "Medium"}},
    {"ro.lmk.use_minfree_levels", {"Performance", "Low memory killer levels", "Medium"}},
    {"ro.malloc.impl", {"Performance", "Memory allocator", "Low"}},

    // Audio Configuration
    {"ro.config.ringtone", {"Audio", "Default ringtone", "Low"}},
    {"ro.config.notification_sound", {"Audio", "Default notification", "Low"}},
    {"ro.config.alarm_alert", {"Audio", "Default alarm", "Low"}},
    {"ro.config.sms_received_sound", {"Audio", "SMS received sound", "Low"}},
    {"ro.config.elder-ringtone", {"Audio", "Elder friendly ringtone", "Low"}},
    {"ro.config.media_vol_default", {"Audio", "Default media volume", "Low"}},

    // Vendor Specific
    {"ro.fota.oem", {"Vendor", "FOTA OEM", "Medium"}},
    {"ro.vendor.build.software.version", {"Vendor", "Vendor software version", "Low"}},
    {"ro.vendor.qti.va_aosp.support", {"Vendor", "QTI VA AOSP support", "Low"}},
    {"ro.netflix.bsp_rev", {"Vendor", "Netflix BSP revision", "Low"}},

    // Hardware Specific
    {"persist.vendor.camera.privapp.list", {"Hardware", "Camera privileged apps", "Medium"}},
    {"vendor.camera.aux.packagelist", {"Hardware", "Auxiliary camera packages", "Medium"}},
    {"persist.vendor.sensors.enable.mag_filter", {"Hardware", "Magnetometer filter", "Low"}},

    // File System
    {"persist.fuse_sdcard", {"FileSystem", "FUSE SD card", "Medium"}},
    {"persist.sys.force_sw_gles", {"FileSystem", "Force software GLES", "Medium"}},
    {"persist.sys.fuse.passthrough.enable", {"FileSystem", "FUSE passthrough", "Medium"}},

    // Framework and Runtime
    {"pm.dexopt.first-boot", {"Framework", "First boot DEX optimization", "Medium"}},
    {"pm.dexopt.boot-after-ota", {"Framework", "OTA DEX optimization", "Medium"}},
    {"pm.dexopt.install", {"Framework", "Install DEX optimization", "Medium"}},
    {"persist.device_config.runtime_native_boot.iorap_perfetto_enable", {"Framework", "Perfetto IORAP", "Medium"}},

    // Testing and Debugging
    {"keyguard.no_require_sim", {"Testing", "Keyguard no SIM requirement", "Low"}},
    {"ro.com.android.dataroaming", {"Testing", "Data roaming setting", "Medium"}},
    {"persist.enable_task_snapshots", {"Testing", "Task snapshots", "Medium"}},
    {"config.disable_rtt", {"Testing", "RTT disable", "Medium"}},

    // Specific to Qualcomm/QCOM
    {"rild.libpath", {"Qualcomm", "RIL library path", "Medium"}},
    {"DEVICE_PROVISIONED", {"Qualcomm", "Device provisioned flag", "Low"}},
    {"qcom.hw.aac.encoder", {"Qualcomm", "Qualcomm AAC encoder", "Low"}},
    {"vendor.mm.enable.qcom_parser", {"Qualcomm", "Qualcomm media parser", "Low"}},
    {"persist.vendor.cne.feature", {"Qualcomm", "CNE feature", "Medium"}},
    {"persist.vendor.radio.atfwd.start", {"Qualcomm", "Radio ATFWD", "Medium"}},

    // Battery and Power
    {"ro.charger.enable_suspend", {"Power", "Charger suspend", "Medium"}},
    {"persist.vendor.cp.taper_term_mv", {"Power", "Taper termination voltage", "Low"}},
    {"persist.vendor.cp.fcc_main_ua", {"Power", "Fast charge current", "Low"}},
    {"persist.vendor.cp.qc3p5_vfloat_offset_uv", {"Power", "Quick charge voltage offset", "Low"}}
};
