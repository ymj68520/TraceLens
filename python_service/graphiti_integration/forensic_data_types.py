"""
Forensic data types for multi-source database records.

Defines dataclasses mirroring the C++ structs used in each analyzer module's
SQLite database, enabling the Python pipeline to read from all per-image DBs.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# =============================================================================
# Events Database (_events.db)
# =============================================================================

@dataclass
class TimelineEvent:
    """Timeline event from the events database."""
    id: int
    timestamp: int
    event_type: str  # CREATED, MODIFIED, ACCESSED, CHANGED, DELETED
    file_path: str
    inode: int = 0
    description: str = ""
    file_size: int = 0
    file_type: str = ""

    @property
    def timestamp_datetime(self) -> Optional[datetime]:
        if self.timestamp and self.timestamp > 0:
            return datetime.fromtimestamp(self.timestamp)
        return None

@dataclass
class EventCluster:
    """Event cluster with AI analysis from the events database."""
    id: int
    timestamp: int
    event_type: str  # CREATED, MODIFIED, ACCESSED, CHANGED, DELETED
    file_path: str
    inode: int = 0
    description: str = ""
    file_size: int = 0
    file_type: str = ""
    # LLM analysis fields
    llm_summary: Optional[str] = None
    llm_description: Optional[str] = None
    llm_keywords: Optional[str] = None
    llm_analyzed_at: Optional[int] = None
    llm_model_used: Optional[str] = None
    llm_is_relevant: bool = False

    @property
    def timestamp_datetime(self) -> Optional[datetime]:
        if self.timestamp and self.timestamp > 0:
            return datetime.fromtimestamp(self.timestamp)
        return None

    @property
    def has_llm_analysis(self) -> bool:
        """Check if this event cluster has LLM analysis."""
        return self.llm_analyzed_at is not None and self.llm_analyzed_at > 0

    @property
    def keywords_list(self) -> list[str]:
        """Parse keywords string into list."""
        if not self.llm_keywords:
            return []
        # Keywords may be comma-separated or JSON array
        keywords = self.llm_keywords.strip()
        if keywords.startswith("["):
            import json
            try:
                return json.loads(keywords)
            except json.JSONDecodeError:
                pass
        return [k.strip() for k in keywords.split(",") if k.strip()]


# =============================================================================
# Raw Database (_raw.db) - additional records beyond FileRecord
# =============================================================================

@dataclass
class PartitionInfo:
    """Partition info from the raw database."""
    id: int
    partition_num: int
    start_offset: int
    length: int
    description: str = ""
    fs_type: str = ""


# =============================================================================
# Windows Database (_windows.db)
# =============================================================================

@dataclass
class WindowsRegistryValue:
    """Windows registry value entry."""
    id: int
    key_path: str
    value_name: str
    value_type: str = ""
    value_data: str = ""
    last_modified: int = 0

@dataclass
class WindowsEventLog:
    """Windows event log entry."""
    id: int
    log_name: str
    event_id: int = 0
    level: str = ""
    source: str = ""
    timestamp: int = 0
    computer: str = ""
    message: str = ""
    user_sid: str = ""

@dataclass
class WindowsPrefetchInfo:
    """Windows prefetch file info."""
    id: int
    executable_name: str
    prefetch_hash: str = ""
    run_count: int = 0
    last_run_time: int = 0
    file_path: str = ""

@dataclass
class WindowsUserInfo:
    """Windows user account info."""
    id: int
    username: str
    sid: str = ""
    full_name: str = ""
    account_type: str = ""
    last_login: int = 0
    login_count: int = 0
    is_disabled: bool = False
    is_locked: bool = False

@dataclass
class WindowsUSBDevice:
    """Windows USB device info."""
    id: int
    device_name: str
    vendor_id: str = ""
    product_id: str = ""
    serial_number: str = ""
    first_connected: int = 0
    last_connected: int = 0
    device_class: str = ""

@dataclass
class WindowsBrowserHistory:
    """Windows browser history entry."""
    id: int
    url: str
    title: str = ""
    visit_count: int = 0
    last_visit: int = 0
    browser_name: str = ""

@dataclass
class WindowsService:
    """Windows service info."""
    id: int
    service_name: str
    display_name: str = ""
    binary_path: str = ""
    start_type: str = ""
    service_type: str = ""
    account: str = ""
    state: str = ""

@dataclass
class WindowsAmcacheEntry:
    """Windows Amcache entry."""
    id: int
    file_path: str
    file_name: str = ""
    sha1: str = ""
    publisher: str = ""
    product_name: str = ""
    install_date: int = 0

@dataclass
class WindowsLnkFile:
    """Windows LNK (shortcut) file info."""
    id: int
    lnk_path: str
    target_path: str = ""
    working_dir: str = ""
    creation_time: int = 0
    modification_time: int = 0
    access_time: int = 0

@dataclass
class WindowsSrumEntry:
    """Windows SRUM (System Resource Usage Monitor) entry."""
    id: int
    app_id: str
    user_sid: str = ""
    bytes_sent: int = 0
    bytes_received: int = 0
    foreground_cycles: int = 0
    timestamp: int = 0


# =============================================================================
# Linux Database (_linux.db)
# =============================================================================

@dataclass
class LinuxLogEntry:
    """Linux log file entry."""
    id: int
    log_file: str
    timestamp: int = 0
    facility: str = ""
    severity: str = ""
    hostname: str = ""
    process_name: str = ""
    pid: int = 0
    message: str = ""

@dataclass
class LinuxUserInfo:
    """Linux user account info."""
    id: int
    username: str
    uid: int = 0
    gid: int = 0
    home_dir: str = ""
    shell: str = ""
    gecos: str = ""
    password_hash: str = ""
    last_password_change: int = 0

@dataclass
class LinuxGroupInfo:
    """Linux group info."""
    id: int
    group_name: str
    gid: int = 0
    members: str = ""

@dataclass
class LinuxLoginRecord:
    """Linux login record (from wtmp/utmp)."""
    id: int
    username: str
    terminal: str = ""
    host: str = ""
    login_time: int = 0
    logout_time: int = 0
    login_type: str = ""

@dataclass
class LinuxShellHistory:
    """Linux shell history entry."""
    id: int
    username: str
    command: str
    timestamp: int = 0
    shell_type: str = ""
    sequence_num: int = 0


# =============================================================================
# Android Database (_android.db)
# =============================================================================

@dataclass
class AndroidContact:
    """Android contact entry."""
    id: int
    display_name: str = ""
    phone_number: str = ""
    email: str = ""
    account_type: str = ""
    account_name: str = ""

@dataclass
class AndroidSMS:
    """Android SMS message."""
    id: int
    address: str = ""
    body: str = ""
    date: int = 0
    date_sent: int = 0
    read: int = 0
    type: int = 0  # 1=received, 2=sent
    service_center: str = ""

@dataclass
class AndroidCallLog:
    """Android call log entry."""
    id: int
    number: str = ""
    date: int = 0
    duration: int = 0
    type: int = 0  # 1=incoming, 2=outgoing, 3=missed
    name: str = ""
    geocoded_location: str = ""

@dataclass
class AndroidChatMessage:
    """Android chat message (WhatsApp/Telegram/WeChat)."""
    id: int
    platform: str  # "whatsapp", "telegram", "wechat"
    sender: str = ""
    receiver: str = ""
    content: str = ""
    timestamp: int = 0
    media_url: str = ""
    media_type: str = ""

@dataclass
class AndroidWifiNetwork:
    """Android WiFi network entry."""
    id: int
    ssid: str
    pre_shared_key: str = ""
    key_mgmt: str = ""
    last_connected: int = 0

@dataclass
class AndroidChromeHistory:
    """Android Chrome browser history."""
    id: int
    url: str
    title: str = ""
    visit_count: int = 0
    last_visit_time: int = 0
    typed_count: int = 0

@dataclass
class AndroidInstalledPackage:
    """Android installed package info."""
    id: int
    package_name: str
    code_path: str = ""
    native_library_path: str = ""
    first_install_time: int = 0
    last_update_time: int = 0
    version: str = ""
    installer: str = ""

@dataclass
class AndroidUsageStat:
    """Android app usage statistics."""
    id: int
    package_name: str
    total_time_foreground: int = 0
    last_time_used: int = 0
    interval_start: int = 0
