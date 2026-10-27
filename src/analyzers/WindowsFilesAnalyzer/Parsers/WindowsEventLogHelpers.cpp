#include "WindowsEventLogParser.h"
#include <boost/property_tree/ptree.hpp>
#include <boost/property_tree/xml_parser.hpp>
#include <sstream>
#include <regex>

namespace EvtxHelpers {
std::string eventLevelToString(uint8_t level) {
    switch(level) {
        case 0: return "LogAlways";
        case 1: return "Critical";
        case 2: return "Error";
        case 3: return "Warning";
        case 4: return "Information";
        case 5: return "Verbose";
        default: return "Unknown";
    }
}
int64_t filetimeToUnixTime(uint64_t value) {
    if (!value || value>2650467743999999999ULL) return 0;
    return static_cast<int64_t>(value/10000000ULL)-11644473600LL;
}
std::string extractUserDataFromXML(const std::string& xml) {
    const std::regex sid("S-[0-9]+(-[0-9]+)+");
    try {
        boost::property_tree::ptree tree;
        std::istringstream stream(xml); boost::property_tree::read_xml(stream,tree);
        auto value=tree.get<std::string>("Event.System.Security.<xmlattr>.UserID", "");
        if(std::regex_match(value,sid)) return value;
        const auto data=tree.get_child_optional("Event.EventData");
        if(data) for(const auto& node:*data) {
            const auto name=node.second.get<std::string>("<xmlattr>.Name", "");
            if(node.first=="Data" && (name=="SubjectUserSid" || name=="UserSid" || name=="UserId")) {
                value=node.second.data();
                if(std::regex_match(value,sid)) return value;
            }
        }
    } catch(const boost::property_tree::ptree_error&) {}
    return {}; // Missing SID is unknown, never a username or a fabricated NULL SID.
}
std::string extractChannelFromXML(const std::string& xml) {
    try {
        boost::property_tree::ptree tree; std::istringstream stream(xml);
        boost::property_tree::read_xml(stream,tree);
        return tree.get<std::string>("Event.System.Channel", "");
    } catch(const boost::property_tree::ptree_error&) { return {}; }
}
std::string getLogSourceFromPath(const std::string& path) {
    const auto slash=path.find_last_of("/\\");
    const auto start=slash==std::string::npos?0:slash+1;
    const auto dot=path.find_last_of('.');
    return dot==std::string::npos || dot<=start ? "Unknown" : path.substr(start,dot-start);
}
}
