#include "FileClassifier.h"
#include "ConfigManager/ConfigManager.h"

// Extension map initialization - moved to separate file for maintainability

void FileClassifier::initializeExtensionMap() {
	// Image files
	std::vector<std::string> imageExts = {
		"jpg", "jpeg", "png", "gif", "bmp", "tiff", "tif", "ico", "svg",
		"webp", "raw", "cr2", "nef", "arw", "dng", "psd", "ai", "eps",
		"heic", "heif", "jfif", "exif",
		// Modern formats
		"avif", "jxl", "webp2", "apng",
		// RAW formats
		"orf", "rw2", "raf", "3fr", "dcr", "k25", "kdc", "mrw", "nrw", "pef", "sr2", "srf", "x3f"
	};
	auto extraImageExts = forensics::ConfigManager::instance().getExtraExtensions("IMAGE");
	imageExts.insert(imageExts.end(), extraImageExts.begin(), extraImageExts.end());

	for (const auto& ext : imageExts) {
		extensionMap_[ext] = FileCategory::IMAGE;
	}

	// Video files
	std::vector<std::string> videoExts = {
		"mp4", "avi", "mkv", "mov", "wmv", "flv", "webm", "m4v", "mpg",
		"mpeg", "3gp", "f4v", "swf", "vob", "ogv", "m2ts", "mts", "ts",
		"divx", "xvid", "rm", "rmvb", "asf",
		// Professional formats
		"mxf", "prores", "dnxhd", "dnxhr",
		// Additional formats
		"mpe", "m2v", "m4p", "qt", "yuv"
	};
	auto extraVideoExts = forensics::ConfigManager::instance().getExtraExtensions("VIDEO");
	videoExts.insert(videoExts.end(), extraVideoExts.begin(), extraVideoExts.end());
	for (const auto& ext : videoExts) {
		extensionMap_[ext] = FileCategory::VIDEO;
	}

	// Audio files
	std::vector<std::string> audioExts = {
		"mp3", "wav", "flac", "aac", "ogg", "wma", "m4a", "opus", "ape",
		"alac", "aiff", "au", "mid", "midi", "ra", "rm", "amr", "ac3",
		// High-fidelity formats
		"dsd", "dsf", "dff",
		// Additional formats
		"mka", "oga", "mogg", "pcm", "aif", "aifc", "caf", "sd2"
	};
	auto extraAudioExts = forensics::ConfigManager::instance().getExtraExtensions("AUDIO");
	audioExts.insert(audioExts.end(), extraAudioExts.begin(), extraAudioExts.end());
	for (const auto& ext : audioExts) {
		extensionMap_[ext] = FileCategory::AUDIO;
	}

	// Document files
	std::vector<std::string> docExts = {
		"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods",
		"odp", "rtf", "txt", "tex", "wpd", "wps", "abw", "pages", "numbers",
		"key", "csv", "epub", "mobi", "fb2", "lit", "pdb"
	};
	auto extraDocExts = forensics::ConfigManager::instance().getExtraExtensions("DOCUMENT");
	docExts.insert(docExts.end(), extraDocExts.begin(), extraDocExts.end());
	for (const auto& ext : docExts) {
		extensionMap_[ext] = FileCategory::DOCUMENT;
	}

	// Archive files
	std::vector<std::string> archiveExts = {
		"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "lzma", "cab", "iso",
		"z", "tgz", "tbz2", "txz", "tlz", "deb", "rpm", "apk", "jar", "war",
		"ear", "par", "arj", "ace", "pak", "sit", "sitx", "dmg", "cpio", "shar"
	};
	auto extraArchiveExts = forensics::ConfigManager::instance().getExtraExtensions("ARCHIVE");
	archiveExts.insert(archiveExts.end(), extraArchiveExts.begin(), extraArchiveExts.end());
	for (const auto& ext : archiveExts) {
		extensionMap_[ext] = FileCategory::ARCHIVE;
	}

	// Executable files
	std::vector<std::string> exeExts = {
		"exe", "dll", "so", "dylib", "app", "bin", "com", "bat", "sh", "cmd",
		"msi", "appimage", "elf", "o", "a", "lib", "obj", "sys", "drv",
		// Shell / OS automation scripts (run directly)
		"vbs", "wsf",
		"ps1", "psm1", "psd1", "bash", "zsh", "csh", "tcsh", "fish"
		// NOTE: interpreted-language sources (py, js, rb, pl, php, lua, tcl)
		// are SOURCE_CODE, not EXECUTABLE — see codeExts below.
	};
	auto extraExeExts = forensics::ConfigManager::instance().getExtraExtensions("EXECUTABLE");
	exeExts.insert(exeExts.end(), extraExeExts.begin(), extraExeExts.end());
	for (const auto& ext : exeExts) {
		extensionMap_[ext] = FileCategory::EXECUTABLE;
	}

	// Database files
	std::vector<std::string> dbExts = {
		"db", "sqlite", "sqlite3", "mdb", "accdb", "db3", "sdb", "sdf", "mdf",
		"ldf", "ndf", "ibd", "myd", "myi", "frm", "fdb", "gdb", "bdf", "kex"
	};
	auto extraDbExts = forensics::ConfigManager::instance().getExtraExtensions("DATABASE");
	dbExts.insert(dbExts.end(), extraDbExts.begin(), extraDbExts.end());
	for (const auto& ext : dbExts) {
		extensionMap_[ext] = FileCategory::DATABASE;
	}

	// Source code files
	std::vector<std::string> codeExts = {
		"c", "cpp", "cc", "cxx", "h", "hpp", "hxx", "java", "cs", "go", "rs",
		"kt", "swift", "scala", "groovy", "clj", "cljs", "hs", "erl", "hrl",
		"ex", "exs", "fs", "fsi", "fsx", "vb", "vbp", "bas", "pas", "pp", "inc",
		// Interpreted-language sources (moved out of EXECUTABLE)
		"py", "js", "ts", "jsx", "tsx", "rb", "pl", "php", "lua", "tcl"
	};
	auto extraCodeExts = forensics::ConfigManager::instance().getExtraExtensions("SOURCE_CODE");
	codeExts.insert(codeExts.end(), extraCodeExts.begin(), extraCodeExts.end());
	for (const auto& ext : codeExts) {
		extensionMap_[ext] = FileCategory::SOURCE_CODE;
	}

	// Web files
	std::vector<std::string> webExts = {
		"html", "htm", "xhtml", "xml", "xsl", "xslt", "css", "scss", "sass", "less",
		"json", "yaml", "yml", "toml", "ini", "cfg", "conf", "htaccess", "sitemap"
	};
	auto extraWebExts = forensics::ConfigManager::instance().getExtraExtensions("WEB");
	webExts.insert(webExts.end(), extraWebExts.begin(), extraWebExts.end());
	for (const auto& ext : webExts) {
		extensionMap_[ext] = FileCategory::WEB;
	}

	// Email files
	std::vector<std::string> emailExts = {
		"eml", "msg", "pst", "ost", "mbox", "mbx", "imap", "pop3", "smtp", "mime"
	};
	auto extraEmailExts = forensics::ConfigManager::instance().getExtraExtensions("EMAIL");
	emailExts.insert(emailExts.end(), extraEmailExts.begin(), extraEmailExts.end());
	for (const auto& ext : emailExts) {
		extensionMap_[ext] = FileCategory::EMAIL;
	}

	// System files (generic)
	std::vector<std::string> systemExts = {
		"sys", "drv", "inf", "reg", "pol", "dat", "ini", "cfg", "conf", "log",
		"dll", "ocx", "cpl", "msc", "scr", "com", "vxd", "ld", "so", "dylib"
	};
	auto extraSystemExts = forensics::ConfigManager::instance().getExtraExtensions("SYSTEM");
	systemExts.insert(systemExts.end(), extraSystemExts.begin(), extraSystemExts.end());
	for (const auto& ext : systemExts) {
		extensionMap_[ext] = FileCategory::SYSTEM;
	}

	// Encrypted files
	std::vector<std::string> encryptedExts = {
		"gpg", "pgp", "asc", "enc", "crypto", "aes", "des", "rsa", "pem", "key", "cer", "crt", "pfx", "p12"
	};
	auto extraEncryptedExts = forensics::ConfigManager::instance().getExtraExtensions("ENCRYPTED");
	encryptedExts.insert(encryptedExts.end(), extraEncryptedExts.begin(), extraEncryptedExts.end());
	for (const auto& ext : encryptedExts) {
		extensionMap_[ext] = FileCategory::ENCRYPTED;
	}
}

void FileClassifier::initializeExtendedExtensionMap() {
	// OS configuration files
	std::vector<std::string> osConfigExts = {
		"conf", "config", "cfg", "ini", "yaml", "yml", "json", "toml", "xml",
		"plist", "props", "properties", "env", "profile", "bashrc", "zshrc",
		"vimrc", "tmux.conf", "fstab", "hosts", "resolv.conf"
	};
	for (const auto& ext : osConfigExts) {
		extendedExtensionMap_[ext] = FileCategory::OS_CONFIG;
	}

	// Boot files
	std::vector<std::string> bootExts = {
		"efi", "vmlinuz", "initrd", "initramfs", "img", "iso", "wim", "esd",
		"grub", "cfg", "menu.lst", "shim", "mbr", "pxe", "sys"
	};
	for (const auto& ext : bootExts) {
		extendedExtensionMap_[ext] = FileCategory::OS_BOOT;
	}

	// Library files
	std::vector<std::string> libExts = {
		"so", "so.1", "so.2", "a", "la", "o", "lo", "dylib", "dll", "ocx",
		"lib", "olb", "rlib", "qlb"
	};
	for (const auto& ext : libExts) {
		extendedExtensionMap_[ext] = FileCategory::OS_LIBRARY;
	}

	// Filesystem journal files
	std::vector<std::string> journalExts = {
		"journal", "log", "jnl", "txn", "wal", "db-shm", "db-wal", "journal"
	};
	for (const auto& ext : journalExts) {
		extendedExtensionMap_[ext] = FileCategory::FS_JOURNAL;
	}

	// Log files
	std::vector<std::string> logExts = {
		"log", "logs", "txt", "out", "err", "debug", "trace"
	};
	for (const auto& ext : logExts) {
		extendedExtensionMap_[ext] = FileCategory::LOG_FILE;
	}

	// Cache files
	std::vector<std::string> cacheExts = {
		"cache", "cch", "tmp", "temp", "swp", "swo", "bak"
	};
	for (const auto& ext : cacheExts) {
		extendedExtensionMap_[ext] = FileCategory::CACHE;
	}

	// Temporary files
	std::vector<std::string> tempExts = {
		"tmp", "temp", "bak", "old", "save", "~", "swp", "swo"
	};
	for (const auto& ext : tempExts) {
		extendedExtensionMap_[ext] = FileCategory::TEMP;
	}

	// Backup files
	std::vector<std::string> backupExts = {
		"bak", "backup", "old", "orig", "save", "~"
	};
	for (const auto& ext : backupExts) {
		extendedExtensionMap_[ext] = FileCategory::BACKUP;
	}

	// Font files
	std::vector<std::string> fontExts = {
		"ttf", "otf", "woff", "woff2", "eot", "pfb", "pfm", "afm"
	};
	for (const auto& ext : fontExts) {
		extendedExtensionMap_[ext] = FileCategory::FONT;
	}

	// Certificate files
	std::vector<std::string> certExts = {
		"cer", "crt", "pem", "key", "pfx", "p12", "der", "csr"
	};
	for (const auto& ext : certExts) {
		extendedExtensionMap_[ext] = FileCategory::CERTIFICATE;
	}
}
