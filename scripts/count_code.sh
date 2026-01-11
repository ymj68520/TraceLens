#!/bin/bash

# ============================================================================
# Code Statistics Script using cloc
# ============================================================================
# A comprehensive script for counting lines of code in the project
# Supports dynamic input and multiple task types
# ============================================================================

# Color definitions for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default exclude directories
DEFAULT_EXCLUDES="build,libs,.git,.claude,node_modules,vendor,third_party"

# Output timestamp
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')

# ============================================================================
# Helper Functions
# ============================================================================

print_header() {
    echo -e "\n${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}${BOLD}  📊 Project Code Statistics Tool                              ${NC}${CYAN}║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}\n"
}

print_section() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}${BOLD}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

check_cloc() {
    if ! command -v cloc &> /dev/null; then
        echo -e "${RED}❌ Error: cloc is not installed!${NC}"
        echo -e "${YELLOW}Install it with:${NC}"
        echo -e "  Ubuntu/Debian: ${GREEN}sudo apt install cloc${NC}"
        echo -e "  macOS:         ${GREEN}brew install cloc${NC}"
        echo -e "  Arch Linux:    ${GREEN}sudo pacman -S cloc${NC}"
        exit 1
    fi
}

show_help() {
    print_header
    echo -e "${BOLD}Usage:${NC} $0 [OPTIONS] [TASK]"
    echo ""
    echo -e "${BOLD}Dynamic Input Options:${NC}"
    echo -e "  ${GREEN}-d, --dir <path>${NC}      Directory to analyze (default: project root)"
    echo -e "  ${GREEN}-e, --exclude <dirs>${NC}  Comma-separated list of directories to exclude"
    echo -e "  ${GREEN}-l, --lang <langs>${NC}    Comma-separated list of languages to include"
    echo -e "  ${GREEN}-f, --format <fmt>${NC}    Output format: text, json, csv, md, xml"
    echo -e "  ${GREEN}-o, --output <file>${NC}  Save output to file"
    echo -e "  ${GREEN}-q, --quiet${NC}           Minimal output"
    echo -e "  ${GREEN}-v, --verbose${NC}         Verbose output"
    echo -e "  ${GREEN}-h, --help${NC}            Show this help message"
    echo ""
    echo -e "${BOLD}Task Types:${NC}"
    echo -e "  ${CYAN}all${NC}           Full project statistics (default)"
    echo -e "  ${CYAN}src${NC}           Source code only (src/ directory)"
    echo -e "  ${CYAN}tests${NC}         Test code only (tests/ directory)"
    echo -e "  ${CYAN}libs${NC}          Library code only (libs/ directory)"
    echo -e "  ${CYAN}docs${NC}          Documentation files (docs/ directory)"
    echo -e "  ${CYAN}by-dir${NC}        Statistics by directory"
    echo -e "  ${CYAN}by-lang${NC}       Statistics by language"
    echo -e "  ${CYAN}diff${NC}          Compare with git HEAD (shows recent changes)"
    echo -e "  ${CYAN}diff-branch${NC}   Compare current branch with main/master"
    echo -e "  ${CYAN}complexity${NC}    Code complexity analysis"
    echo -e "  ${CYAN}history${NC}       Show code growth over recent commits"
    echo -e "  ${CYAN}report${NC}        Generate comprehensive markdown report"
    echo -e "  ${CYAN}summary${NC}       Quick summary statistics"
    echo -e "  ${CYAN}interactive${NC}   Interactive mode - choose task dynamically"
    echo ""
    echo -e "${BOLD}Examples:${NC}"
    echo -e "  $0                           # Full project statistics"
    echo -e "  $0 src                       # Source code only"
    echo -e "  $0 -d ./src/core -l C++,C    # Custom directory, C/C++ only"
    echo -e "  $0 -f md -o report.md all    # Markdown report to file"
    echo -e "  $0 interactive               # Interactive mode"
    echo ""
}

# ============================================================================
# Task Functions
# ============================================================================

task_all() {
    print_section "📁 Full Project Statistics"
    cd "$TARGET_DIR"
    cloc . --exclude-dir=$EXCLUDES $LANG_FILTER $FORMAT_OPTS $VERBOSE_OPTS
}

task_src() {
    print_section "📦 Source Code Statistics (src/)"
    if [ -d "$TARGET_DIR/src" ]; then
        cloc "$TARGET_DIR/src" --exclude-dir=$EXCLUDES $LANG_FILTER $FORMAT_OPTS $VERBOSE_OPTS
    else
        echo -e "${YELLOW}⚠️  src/ directory not found${NC}"
    fi
}

task_tests() {
    print_section "🧪 Test Code Statistics (tests/)"
    if [ -d "$TARGET_DIR/tests" ]; then
        cloc "$TARGET_DIR/tests" $LANG_FILTER $FORMAT_OPTS $VERBOSE_OPTS
    else
        echo -e "${YELLOW}⚠️  tests/ directory not found${NC}"
    fi
}

task_libs() {
    print_section "📚 Library Code Statistics (libs/)"
    if [ -d "$TARGET_DIR/libs" ]; then
        cloc "$TARGET_DIR/libs" $LANG_FILTER $FORMAT_OPTS $VERBOSE_OPTS
    else
        echo -e "${YELLOW}⚠️  libs/ directory not found${NC}"
    fi
}

task_docs() {
    print_section "📝 Documentation Statistics (docs/)"
    if [ -d "$TARGET_DIR/docs" ]; then
        cloc "$TARGET_DIR/docs" --include-lang=Markdown,Text,reStructuredText $FORMAT_OPTS $VERBOSE_OPTS
    else
        echo -e "${YELLOW}⚠️  docs/ directory not found${NC}"
    fi
}

task_by_dir() {
    print_section "📊 Statistics by Directory"
    cd "$TARGET_DIR"
    
    echo -e "${BOLD}Top-level directories:${NC}\n"
    for dir in */; do
        if [[ ! "$EXCLUDES" =~ "${dir%/}" ]]; then
            echo -e "${CYAN}━━━ $dir ━━━${NC}"
            cloc "$dir" --quiet --exclude-dir=$EXCLUDES 2>/dev/null | tail -n +3
            echo ""
        fi
    done
}

task_by_lang() {
    print_section "🔤 Statistics by Language"
    cd "$TARGET_DIR"
    cloc . --exclude-dir=$EXCLUDES --by-file-by-lang $VERBOSE_OPTS
}

task_diff() {
    print_section "🔄 Changes Since Last Commit (HEAD)"
    cd "$TARGET_DIR"
    if git rev-parse --git-dir > /dev/null 2>&1; then
        cloc --git --diff HEAD~1 HEAD --exclude-dir=$EXCLUDES $FORMAT_OPTS
    else
        echo -e "${YELLOW}⚠️  Not a git repository${NC}"
    fi
}

task_diff_branch() {
    print_section "🌿 Branch Comparison (vs main/master)"
    cd "$TARGET_DIR"
    if git rev-parse --git-dir > /dev/null 2>&1; then
        # Find the default branch
        DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | cut -d: -f2 | xargs || echo "main")
        CURRENT_BRANCH=$(git branch --show-current)
        
        if [ "$CURRENT_BRANCH" != "$DEFAULT_BRANCH" ]; then
            echo -e "${CYAN}Comparing $CURRENT_BRANCH with $DEFAULT_BRANCH${NC}\n"
            cloc --git --diff "$DEFAULT_BRANCH" "$CURRENT_BRANCH" --exclude-dir=$EXCLUDES $FORMAT_OPTS
        else
            echo -e "${YELLOW}⚠️  Already on $DEFAULT_BRANCH branch${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Not a git repository${NC}"
    fi
}

task_complexity() {
    print_section "🧮 Code Complexity Analysis"
    cd "$TARGET_DIR"
    
    echo -e "${BOLD}File Count by Extension:${NC}"
    find . -type f -name "*.*" \
        ! -path "./build/*" \
        ! -path "./libs/*" \
        ! -path "./.git/*" \
        ! -path "./node_modules/*" \
        2>/dev/null | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -20
    
    echo -e "\n${BOLD}Largest Source Files (by lines):${NC}"
    find . -type f \( -name "*.cpp" -o -name "*.h" -o -name "*.c" -o -name "*.hpp" \) \
        ! -path "./build/*" \
        ! -path "./libs/*" \
        2>/dev/null | xargs wc -l 2>/dev/null | sort -rn | head -15
    
    echo -e "\n${BOLD}Detailed Statistics:${NC}"
    cloc . --exclude-dir=$EXCLUDES --by-percent cmb $VERBOSE_OPTS
}

task_history() {
    print_section "📈 Code Growth History (Last 10 Commits)"
    cd "$TARGET_DIR"
    
    if git rev-parse --git-dir > /dev/null 2>&1; then
        echo -e "${BOLD}Lines of code per commit:${NC}\n"
        
        i=0
        for commit in $(git log --oneline -10 --format="%H"); do
            if [ $i -gt 0 ]; then
                prev_commit="$commit"
                i=$((i+1))
                continue
            fi
            
            date=$(git show -s --format="%ci" "$commit" | cut -d' ' -f1)
            msg=$(git show -s --format="%s" "$commit" | cut -c1-40)
            
            echo -e "${CYAN}$date${NC} - ${msg}..."
            git show --stat "$commit" | tail -1
            
            i=$((i+1))
        done
    else
        echo -e "${YELLOW}⚠️  Not a git repository${NC}"
    fi
}

task_report() {
    print_section "📋 Generating Comprehensive Report"
    
    REPORT_FILE="${OUTPUT_FILE:-$TARGET_DIR/docs/Code_Statistics_Report.md}"
    mkdir -p "$(dirname "$REPORT_FILE")"
    
    echo "# Code Statistics Report" > "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    echo "**Generated:** $(date '+%Y-%m-%d %H:%M:%S')" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    
    echo "## Project Overview" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
    cloc "$TARGET_DIR" --exclude-dir=$EXCLUDES --quiet >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    
    echo "## Source Code (src/)" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    if [ -d "$TARGET_DIR/src" ]; then
        echo '```' >> "$REPORT_FILE"
        cloc "$TARGET_DIR/src" --exclude-dir=$EXCLUDES --quiet >> "$REPORT_FILE"
        echo '```' >> "$REPORT_FILE"
    else
        echo "_No src/ directory found_" >> "$REPORT_FILE"
    fi
    echo "" >> "$REPORT_FILE"
    
    echo "## Test Code (tests/)" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    if [ -d "$TARGET_DIR/tests" ]; then
        echo '```' >> "$REPORT_FILE"
        cloc "$TARGET_DIR/tests" --quiet >> "$REPORT_FILE"
        echo '```' >> "$REPORT_FILE"
    else
        echo "_No tests/ directory found_" >> "$REPORT_FILE"
    fi
    echo "" >> "$REPORT_FILE"
    
    echo "## Statistics by Language" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
    cloc "$TARGET_DIR" --exclude-dir=$EXCLUDES --quiet --by-percent cmb >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
    
    echo -e "${GREEN}✅ Report saved to: $REPORT_FILE${NC}"
}

task_summary() {
    print_section "⚡ Quick Summary"
    cd "$TARGET_DIR"
    
    # Get total lines
    TOTAL=$(cloc . --exclude-dir=$EXCLUDES --quiet --csv | tail -1)
    
    echo -e "${BOLD}Project:${NC} $(basename "$TARGET_DIR")"
    echo -e "${BOLD}Path:${NC} $TARGET_DIR"
    echo ""
    
    cloc . --exclude-dir=$EXCLUDES --quiet | head -20
}

task_interactive() {
    print_header
    
    echo -e "${BOLD}Select a task:${NC}\n"
    echo -e "  ${CYAN}1)${NC}  Full project statistics"
    echo -e "  ${CYAN}2)${NC}  Source code only (src/)"
    echo -e "  ${CYAN}3)${NC}  Test code only (tests/)"
    echo -e "  ${CYAN}4)${NC}  Library code (libs/)"
    echo -e "  ${CYAN}5)${NC}  Documentation (docs/)"
    echo -e "  ${CYAN}6)${NC}  Statistics by directory"
    echo -e "  ${CYAN}7)${NC}  Statistics by language"
    echo -e "  ${CYAN}8)${NC}  Git diff (recent changes)"
    echo -e "  ${CYAN}9)${NC}  Branch comparison"
    echo -e "  ${CYAN}10)${NC} Code complexity analysis"
    echo -e "  ${CYAN}11)${NC} Code growth history"
    echo -e "  ${CYAN}12)${NC} Generate markdown report"
    echo -e "  ${CYAN}13)${NC} Quick summary"
    echo -e "  ${CYAN}14)${NC} Custom directory analysis"
    echo -e "  ${CYAN}0)${NC}  Exit"
    echo ""
    
    read -p "Enter your choice [0-14]: " choice
    
    case $choice in
        1)  task_all ;;
        2)  task_src ;;
        3)  task_tests ;;
        4)  task_libs ;;
        5)  task_docs ;;
        6)  task_by_dir ;;
        7)  task_by_lang ;;
        8)  task_diff ;;
        9)  task_diff_branch ;;
        10) task_complexity ;;
        11) task_history ;;
        12) task_report ;;
        13) task_summary ;;
        14)
            read -p "Enter directory path: " custom_dir
            if [ -d "$custom_dir" ]; then
                print_section "📁 Custom Directory: $custom_dir"
                cloc "$custom_dir" --exclude-dir=$EXCLUDES $LANG_FILTER $FORMAT_OPTS
            else
                echo -e "${RED}❌ Directory not found: $custom_dir${NC}"
            fi
            ;;
        0)  echo -e "${GREEN}Goodbye!${NC}"; exit 0 ;;
        *)  echo -e "${RED}Invalid option${NC}"; task_interactive ;;
    esac
    
    echo ""
    read -p "Run another task? [y/N]: " again
    if [[ "$again" =~ ^[Yy]$ ]]; then
        task_interactive
    fi
}

# ============================================================================
# Main Script
# ============================================================================

# Initialize variables
TARGET_DIR="$PROJECT_ROOT"
EXCLUDES="$DEFAULT_EXCLUDES"
LANG_FILTER=""
FORMAT_OPTS=""
OUTPUT_FILE=""
VERBOSE_OPTS=""
QUIET_MODE=false
TASK="all"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--dir)
            TARGET_DIR="$(realpath "$2")"
            shift 2
            ;;
        -e|--exclude)
            EXCLUDES="$2"
            shift 2
            ;;
        -l|--lang)
            LANG_FILTER="--include-lang=$2"
            shift 2
            ;;
        -f|--format)
            case $2 in
                json) FORMAT_OPTS="--json" ;;
                csv)  FORMAT_OPTS="--csv" ;;
                md)   FORMAT_OPTS="--md" ;;
                xml)  FORMAT_OPTS="--xml" ;;
                text) FORMAT_OPTS="" ;;
                *)    echo -e "${RED}Unknown format: $2${NC}"; exit 1 ;;
            esac
            shift 2
            ;;
        -o|--output)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        -q|--quiet)
            QUIET_MODE=true
            VERBOSE_OPTS="--quiet"
            shift
            ;;
        -v|--verbose)
            VERBOSE_OPTS="--v"
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            # It's a task name
            TASK="$1"
            shift
            ;;
    esac
done

# Check prerequisites
check_cloc

# Redirect output to file if specified
if [ -n "$OUTPUT_FILE" ] && [ "$TASK" != "report" ]; then
    exec > >(tee "$OUTPUT_FILE")
fi

# Print header unless quiet mode
if [ "$QUIET_MODE" = false ]; then
    print_header
    echo -e "${BOLD}Target Directory:${NC} $TARGET_DIR"
    echo -e "${BOLD}Excluded:${NC} $EXCLUDES"
    [ -n "$LANG_FILTER" ] && echo -e "${BOLD}Language Filter:${NC} $LANG_FILTER"
fi

# Execute the selected task
case $TASK in
    all)         task_all ;;
    src)         task_src ;;
    tests)       task_tests ;;
    libs)        task_libs ;;
    docs)        task_docs ;;
    by-dir)      task_by_dir ;;
    by-lang)     task_by_lang ;;
    diff)        task_diff ;;
    diff-branch) task_diff_branch ;;
    complexity)  task_complexity ;;
    history)     task_history ;;
    report)      task_report ;;
    summary)     task_summary ;;
    interactive) task_interactive ;;
    *)
        echo -e "${RED}❌ Unknown task: $TASK${NC}"
        echo -e "Run ${GREEN}$0 --help${NC} for usage information"
        exit 1
        ;;
esac

if [ "$QUIET_MODE" = false ]; then
    echo -e "\n${GREEN}✅ Done!${NC}"
fi
