#include "FileClassifier.h"

// Path and filename pattern initialization - moved to separate file for maintainability

void FileClassifier::initializePathPatterns() {
	// OS configuration paths
	osConfigPaths_ = {
		"/etc/",
		"/etc/default/",
		"/etc/sysconfig/",
		"/etc/conf.d/",
		"/etc/systemd/",
		"/etc/systemd/system/",
		"/etc/systemd/user/",
		"/etc/init.d/",
		"/etc/rc.d/",
		"/etc/security/",
		"/etc/pam.d/",
		"/etc/ssh/",
		"/etc/ssl/",
		"/etc/X11/",
		"/etc/network/",
		"/etc/NetworkManager/",
		"/etc/modprobe.d/",
		"/etc/modules-load.d/",
		"/etc/udev/",
		"/etc/profile.d/",
		"/etc/bash_completion.d/",
		"/etc/apt/",
		"/etc/yum.repos.d/",
		"/etc/zypp/",
		"/etc/cron.d/",
		"/etc/cron.daily/",
		"/etc/cron.hourly/",
		"/etc/cron.weekly/",
		"/etc/cron.monthly/",
		"/etc/sudoers.d/",
		"/etc/nginx/",
		"/etc/apache2/",
		"/etc/httpd/",
		"/etc/mysql/",
		"/etc/postgresql/",
		"/etc/redis/",
		"/etc/docker/",
		"/etc/kubernetes/",
		"/Library/Preferences/",
		"/Library/Application Support/",
		"/private/etc/",
		"C:/Windows/System32/config/",
		"C:/Windows/System32/drivers/etc/",
		"C:/ProgramData/",
		"Windows/System32/config/",
		"Windows/inf/"
	};

	// Boot paths
	bootPaths_ = {
		"/boot/",
		"/boot/grub/",
		"/boot/grub2/",
		"/boot/efi/",
		"/EFI/",
		"/EFI/BOOT/",
		"/EFI/Microsoft/Boot/",
		"/System/Library/Extensions/",
		"/lib/modules/",
		"/lib/firmware/",
		"C:/EFI/",
		"C:/Boot/",
		"Windows/System32/drivers/"
	};

	// Library paths
	libraryPaths_ = {
		"/usr/lib/",
		"/usr/lib64/",
		"/usr/local/lib/",
		"/lib/",
		"/lib64/",
		"/opt/",
		"/usr/X11R6/lib/",
		"/System/Library/",
		"/Library/Frameworks/",
		"C:/Windows/System32/",
		"C:/Windows/SysWOW64/",
		"C:/Program Files/Common Files/"
	};

	// Log paths
	logPaths_ = {
		"/var/log/",
		"/var/adm/",
		"/var/audit/",
		"/Library/Logs/",
		"/Users/",
		"/home/",
		"C:/Windows/Logs/",
		"C:/ProgramData/Logs/",
		"C:/Windows/Temp/",
		"C:/Windows/Debug/",
		"Windows/Panther/",
		"Windows/Minidump/"
	};

	// Cache paths
	cachePaths_ = {
		"/var/cache/",
		"/tmp/",
		"/var/tmp/",
		"/Library/Caches/",
		"~/Library/Caches/",
		"C:/Windows/Temp/",
		"C:/Users/",
		"AppData/Local/Temp/",
		"AppData/Local/Microsoft/Windows/INetCache/"
	};

	// Temp paths
	tempPaths_ = {
		"/tmp/",
		"/var/tmp/",
		"/temp/",
		"C:/Windows/Temp/",
		"C:/Users/",
		"AppData/Local/Temp/",
		"~/tmp/",
		"~/temp/"
	};
}

void FileClassifier::initializeFilenamePatterns() {
	// System configuration files
	systemConfigFiles_ = {
		"passwd", "shadow", "group", "gshadow", "hosts", "hostname",
		"resolv.conf", "fstab", "mtab", "crontab", "inittab", "sysctl.conf",
		"nginx.conf", "httpd.conf", "apache2.conf", "my.cnf", "postgresql.conf",
		"redis.conf", "docker-compose.yml", "Dockerfile", ".env", ".bashrc",
		".zshrc", ".profile", ".bash_profile", ".vimrc", ".tmux.conf",
		"ssh_config", "sshd_config", "sudoers", "login.defs", "limits.conf",
		"rsyslog.conf", "syslog.conf", "logrotate.conf", "pacman.conf",
		"package-manager", "yum.conf", "apt.conf", "dpkg.cfg", "grub.cfg",
		"menu.lst", "lilo.conf", "fstab", "mtab", "mke2fs.conf", "e2fsck.conf",
		"iproute2/", "network/interfaces", "ifcfg-", "netplan/", "NetworkManager/",
		"systemd/", ".service", ".socket", ".timer", ".mount", ".automount",
		".swap", ".target", ".path", ".slice", ".scope"
	};

	// Boot files
	bootFiles_ = {
		"vmlinuz", "initrd", "initramfs", "System.map", "config",
		"grub.cfg", "grub.conf", "menu.lst", "lilo.conf", "elilo.conf",
		"boot.ini", "bcdedit", "bootmgr", "winload.exe", "ntldr",
		"EFI/", "BOOT/", ".efi", "bootx64.efi", "bootia32.efi",
		"kernel", "kernel.img", "zImage", "bzImage", "uImage",
		"xen.gz", "hypervisor.img"
	};
}
