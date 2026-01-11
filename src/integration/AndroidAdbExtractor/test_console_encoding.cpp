#include "adbExtractor.h"
#include <iostream>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#endif

int main() {
    // Initialize console encoding
    initializeConsoleEncoding();

    std::cout << "=== Windows Console Encoding Test ===" << std::endl;
    std::cout << "=== Windows 控制台 编码 测试 ===" << std::endl;
    std::cout << "This test verifies that special characters display correctly on Windows console." << std::endl;

    // Test various special characters and status indicators
    std::cout << "\n1. Testing status indicators:" << std::endl;
    std::cout << "   [OK] Success indicator" << std::endl;
    std::cout << "   [FAIL] Failure indicator" << std::endl;
    std::cout << "   [INFO] Information indicator" << std::endl;

    std::cout << "\n2. Testing root privilege messages:" << std::endl;
    std::cout << "   Checking root privilege status..." << std::endl;
    std::cout << "   [OK] Already have root privileges" << std::endl;
    std::cout << "   No root privileges currently, attempting to acquire..." << std::endl;
    std::cout << "   [OK] Root access acquired (via adb root)" << std::endl;

    std::cout << "\n3. Testing ADB connection messages:" << std::endl;
    std::cout << "   Connected to ADB Server at 127.0.0.1:5037" << std::endl;
    std::cout << "   Found 1 device(s)" << std::endl;
    std::cout << "   Using device: emulator-5554" << std::endl;

    std::cout << "\n4. Testing file extraction messages:" << std::endl;
    std::cout << "   Starting extraction: /system/build.prop" << std::endl;
    std::cout << "   Skipping: /system/build.prop (already complete)" << std::endl;
    std::cout << "   Extraction successful: ./extracted_android_data/system/build.prop" << std::endl;

    std::cout << "\n5. Testing special characters (should display correctly if UTF-8 is working):" << std::endl;
    std::cout << "   Special symbols: \xE2\x98\x86 \xE2\x98\x85 \xE2\x97\x8F \xE2\x97\x86" << std::endl; // Stars and bullets

    std::cout << "\n=== Test completed ===" << std::endl;
    std::cout << "If all characters display correctly, the encoding fix is working." << std::endl;

    return 0;
}