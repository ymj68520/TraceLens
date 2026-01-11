@echo off
echo === Windows Console Encoding Test Script ===
echo.

REM Check if we're on Windows
if not defined OS (
    echo Error: This script is designed for Windows only.
    pause
    exit /b 1
)

echo This script will test the Windows console encoding fixes for AndroidAdbExtractor.
echo.

REM Try to compile the test encoding program
echo Compiling console encoding test...
g++ -std=c++17 -o test_console_encoding.exe test_console_encoding.cpp adbExtractor.cpp adbClient.cpp -lws2_32

if %ERRORLEVEL% neq 0 (
    echo Error: Failed to compile test program.
    echo Please ensure you have g++ and all required dependencies installed.
    pause
    exit /b 1
)

echo Compilation successful!
echo.

REM Run the test
echo Running console encoding test...
echo.
test_console_encoding.exe

echo.
echo Test completed. Please check if all special characters display correctly.
echo.

REM Try to compile the main programs
echo Compiling main programs...
g++ -std=c++17 -o adbTest.exe adbTest.cpp adbExtractor.cpp adbClient.cpp -lws2_32

if %ERRORLEVEL% neq 0 (
    echo Error: Failed to compile main programs.
    pause
    exit /b 1
)

echo Main programs compiled successfully!
echo.
echo You can now test the ADB extractor with:
echo   adbTest.exe
echo.
pause