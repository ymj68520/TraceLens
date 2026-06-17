// FirewallSecurityLogParser.cpp
// Parser for firewall and security product logs (UFW, firewalld, fail2ban, ClamAV, rkhunter, OSSEC, AIDE)
// Phase 11: Database, Email, VPN, DNS, Firewall & Security Product Logs

#include "FirewallSecurityLogParser.h"
#include <sstream>
#include <algorithm>
#include <regex>
#include <map>
#include <set>

namespace forensics {
namespace linux {

// ============================================================================
// Auto-detection

// FirewallSecurityLogParser.cpp
// Implementation split across two sibling files for maintainability:
//   - FirewallSecurityLogParser_Firewall.cpp         (UFW/firewalld + analyzeFirewallSecurity)
//   - FirewallSecurityLogParser_SecurityProducts.cpp  (fail2ban/clamav/rkhunter/ossec/aide + analyzeSecurityProduct)

} // namespace linux
} // namespace forensics
