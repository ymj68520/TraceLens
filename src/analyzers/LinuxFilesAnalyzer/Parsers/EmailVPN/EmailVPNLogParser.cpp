// EmailVPNLogParser.cpp
// Parser for email and VPN service logs (postfix, exim, dovecot, OpenVPN, WireGuard)
// Phase 11: Database, Email, VPN, DNS, Firewall & Security Product Logs

#include "EmailVPNLogParser.h"
#include <sstream>
#include <algorithm>
#include <regex>
#include <map>
#include <set>

namespace forensics {
namespace linux {

// EmailVPNLogParser.cpp
// Implementation split across two sibling files:
//   - EmailVPNLogParser_Email.cpp  (postfix/exim/dovecot + analyzeEmailSecurity)
//   - EmailVPNLogParser_VPN.cpp    (openvpn/wireguard + analyzeVPNSecurity)

} // namespace linux
} // namespace forensics
