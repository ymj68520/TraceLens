#pragma once

#include <filesystem>
#include <vector>

#include "IFileExtractor.h"
#include "MobileEvidencePackage.h"

class ThunderForensicBackupExtractor;
class AndroidAnalysisDatabase;

// Parses a ThunderForensic (雷电手机快取) Android extraction container and
// persists every discovered artifact into the vendor-neutral mobile backup
// tables plus the standard Android artifact tables (installed_apps,
// wifi_networks, contacts, call_logs, sms_messages, device_identifiers).
//
// Supported members:
//   ThunderForensic.json      manifest (brand/model/time/software)
//   PhoneData/*.json          vendor artifact documents
//   LogData/*.log             system log inventory
//   sdcard/**                 media/file payload inventory
//   data/evidence_*           ThunderForensic case databases (project folder)
//   wifi.xml                  shared_prefs WiFi fallback (vivo)
//   note.zip / encryptNote.zip  encrypted note archive inventory
//   .backup                   ThunderForensic marker
//   <package>.tar/**, <package>.ab/**  per-app data trees
bool analyzeThunderForensicBackup(ThunderForensicBackupExtractor& source,
                                  AndroidAnalysisDatabase& output);

// Extraction-stage entry point: the same parsing rules, but the result is a
// unified package instead of a written database. analyzeThunderForensicBackup
// delegates here, so the two paths cannot drift apart.
// `caseProvenanceOut` receives the case-database provenance rows that the
// analysis stage must persist separately from package records.
bool buildPackageFromThunderForensic(
    ThunderForensicBackupExtractor& source, mobile_evidence::Package& out,
    std::vector<AndroidSourceProvenance>& caseProvenanceOut);
