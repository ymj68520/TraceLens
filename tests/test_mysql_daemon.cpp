#include <iostream>
#include "analyzers/DatabaseAnalyzer/Parsers/MySQLAnalyzer.h"

int main() {
    using namespace ForensicAnalyzer::Database;
    
    MySQLAnalyzer analyzer;
    // We expect /var/lib/mysql to exist on the system for a quick test if no custom fixture exists
    std::string testDir = "/var/lib/mysql";
    
    std::cout << "Attempting to open: " << testDir << std::endl;
    if (!analyzer.open(testDir)) {
        std::cerr << "Failed to open directory (maybe no permission or not mysql dir): " << analyzer.getLastError() << std::endl;
        return 0; // Skip test if environment doesn't have a testable mysql dir
    }
    
    std::cout << "Successfully opened MySQL config. Version: " << analyzer.getVersion() << std::endl;
    
    auto tables = analyzer.getTables();
    std::cout << "Found " << tables.size() << " tables." << std::endl;
    
    if (!tables.empty()) {
        std::cout << "Attempting to extract records from: " << tables[0].name << std::endl;
        auto records = analyzer.getRecords(tables[0].name, 5);
        
        std::cout << "Extracted " << records.size() << " records." << std::endl;
        for (const auto& rec : records) {
            std::cout << "Row: ";
            for (const auto& [k, v] : rec.values) {
                std::cout << k << "=" << v << " | ";
            }
            std::cout << std::endl;
        }
    }
    
    analyzer.close();
    return 0;
}
