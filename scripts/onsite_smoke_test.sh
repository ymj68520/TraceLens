#!/usr/bin/env bash
# =============================================================================
# 现场冒烟测试脚本 — 取证项目功能验证（不依赖 AI）
#
# 用途：在甲方现场，AI/LLM 不可用的情况下，验证取证系统全部功能正常。
#       这是"真实测试"——会真正创建分析任务、等待完成、检查数据库产物、
#       验证 AI 降级行为，而不是只 ping 一下 health。
#
# 前提：服务已通过 ./start.sh 或 ./scripts/start_all_services.sh 启动。
#
# 用法：
#   bash onsite_smoke_test.sh                          # 交互式引导（推荐首次）
#   bash onsite_smoke_test.sh /path/to/image.E01       # 直接指定镜像
#   bash onsite_smoke_test.sh /path/to/image.E01 --scenarios windows,linux
#
# 选项：
#   --scenarios LIST   逗号分隔的平台分析：android,windows,linux,server_cloud
#   --timeout N        等待任务完成的超时秒数（默认 1800 = 30 分钟）
#   --cpp-url URL      C++ 服务地址（默认 http://localhost:8080）
#   --py-url URL       Python 服务地址（默认 http://localhost:8090）
#   --keep-task        测试完不删除任务（默认清理）
# =============================================================================

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------- 配置 ----------
CPP_URL="${CPP_URL:-http://localhost:8080}"
PY_URL="${PY_URL:-http://localhost:8090}"
IMAGE_PATH=""
SCENARIOS=""
TASK_TIMEOUT=1800
KEEP_TASK=false

# ---------- 颜色 ----------
if [ -t 1 ]; then
    C_RED='\033[0;31m'; C_GRN='\033[0;32m'; C_YEL='\033[1;33m'
    C_BLU='\033[0;34m'; C_CYA='\033[0;36m'; C_BLD='\033[1m'; C_DIM='\033[2m'; C_RST='\033[0m'
else
    C_RED=''; C_GRN=''; C_YEL=''; C_BLU=''; C_CYA=''; C_BLD=''; C_DIM=''; C_RST=''
fi

# ---------- 计数 ----------
PASS=0; FAIL=0; WARN=0; SKIP=0
RESULTS_FILE="/tmp/onsite_smoke_results_$(date +%Y%m%d_%H%M%S).log"
: > "$RESULTS_FILE"

# ---------- 工具函数 ----------
log_pass() { echo -e "  ${C_GRN}✓ PASS${C_RST} $1"; PASS=$((PASS+1)); echo "PASS | $1" >> "$RESULTS_FILE"; }
log_fail() { echo -e "  ${C_RED}✗ FAIL${C_RST} $1"; FAIL=$((FAIL+1)); echo "FAIL | $1" >> "$RESULTS_FILE"; }
log_warn() { echo -e "  ${C_YEL}⚠ WARN${C_RST} $1"; WARN=$((WARN+1)); echo "WARN | $1" >> "$RESULTS_FILE"; }
log_skip() { echo -e "  ${C_DIM}○ SKIP${C_RST} $1"; SKIP=$((SKIP+1)); echo "SKIP | $1" >> "$RESULTS_FILE"; }
section()  { echo -e "\n${C_CYA}${C_BLD}━━━ $1 ━━━${C_RST}"; echo "" >> "$RESULTS_FILE"; echo "=== $1 ===" >> "$RESULTS_FILE"; }

# HTTP 状态码检查（不输出 body，避免敏感数据打印）
# 用法: check_http "名称" "url" "期望状态码" [--method POST --data 'json']
check_http() {
    local name="$1" url="$2" expect="$3"; shift 3
    local method="GET" data=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --method) method="$2"; shift 2;;
            --data)   data="$2"; shift 2;;
            *) shift;;
        esac
    done
    local code
    if [ "$method" = "POST" ]; then
        code=$(curl -s -m 15 -o /dev/null -w "%{http_code}" -X POST "$url" \
              -H "Content-Type: application/json" -d "$data" 2>/dev/null || echo "000")
    else
        code=$(curl -s -m 15 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    fi
    if [ "$code" = "$expect" ]; then
        log_pass "$name (HTTP $code)"
        return 0
    else
        log_fail "$name — 期望 HTTP $expect，实际 $code"
        return 1
    fi
}

# JSON 字段提取（兼容无 jq 的环境，优先用 jq）
jval() { jq -r "$1" 2>/dev/null || python3 -c "import sys,json; print(json.load(sys.stdin)$2)" 2>/dev/null; }

# ---------- 参数解析 ----------
while [ $# -gt 0 ]; do
    case "$1" in
        --scenarios) SCENARIOS="$2"; shift 2;;
        --timeout)   TASK_TIMEOUT="$2"; shift 2;;
        --cpp-url)   CPP_URL="$2"; shift 2;;
        --py-url)    PY_URL="$2"; shift 2;;
        --keep-task) KEEP_TASK=true; shift;;
        -h|--help)
            sed -n '2,30p' "$0"; exit 0;;
        --*) echo "未知选项: $1"; exit 1;;
        *)  IMAGE_PATH="$1"; shift;;
    esac
done

# ---------- 交互式引导（无参数时）----------
if [ -z "$IMAGE_PATH" ]; then
    echo -e "${C_CYA}${C_BLD}╔════════════════════════════════════════════════════════════╗${C_RST}"
    echo -e "${C_CYA}${C_BLD}║   取证项目 — 现场功能冒烟测试（AI 不可用场景）            ║${C_RST}"
    echo -e "${C_CYA}${C_BLD}╚════════════════════════════════════════════════════════════╝${C_RST}"
    echo
    echo -e "${C_BLD}本脚本会：${C_RST}"
    echo -e "  1. 检查服务健康与配置"
    echo -e "  2. ${C_YEL}真实创建分析任务${C_RST}并等待完成（不是假数据）"
    echo -e "  3. 检查数据库产物（raw/events/files 是否有真实数据）"
    echo -e "  4. 验证非 AI 功能（时间线/统计/搜索/导出）"
    echo -e "  5. 验证 ${C_YEL}AI 降级行为${C_RST}（不可用时不崩溃）"
    echo
    echo -e "${C_BLD}请输入镜像路径（E01/DD/raw/Android data目录）:${C_RST}"
    read -rp "  > " IMAGE_PATH
    [ -z "$IMAGE_PATH" ] && { echo -e "${C_RED}未提供镜像路径，退出${C_RST}"; exit 1; }
    echo
    echo -e "${C_BLD}要测试哪些平台专项分析？（逗号分隔，回车跳过）${C_RST}"
    echo -e "  ${C_DIM}可选: android, windows, linux, server_cloud${C_RST}"
    read -rp "  > " SCENARIOS
    echo
fi

# 校验镜像存在
if [ ! -e "$IMAGE_PATH" ]; then
    echo -e "${C_RED}✗ 镜像不存在: $IMAGE_PATH${C_RST}"
    exit 1
fi

# 构造 scenarios JSON 数组
SCEN_JSON="[]"
if [ -n "$SCENARIOS" ]; then
    SCEN_JSON="["
    IFS=',' read -ra SCARR <<< "$SCENARIOS"
    for s in "${SCARR[@]}"; do
        s=$(echo "$s" | xargs)  # trim
        SCEN_JSON="$SCEN_JSON\"$s\","
    done
    SCEN_JSON="${SCEN_JSON%,}]"
fi

echo -e "${C_DIM}镜像: $IMAGE_PATH${C_RST}"
echo -e "${C_DIM}平台: ${SCENARIOS:-（无）}${C_RST}"
echo -e "${C_DIM}结果日志: $RESULTS_FILE${C_RST}"

# ============================================================
# 阶段 0：环境与配置预检
# ============================================================
section "阶段 0：环境与配置预检"

# 0.1 命令行工具
for cmd in curl python3 sqlite3; do
    if command -v $cmd >/dev/null 2>&1; then
        log_pass "工具可用: $cmd ($(command -v $cmd))"
    else
        log_fail "缺少工具: $cmd — 请先安装"
    fi
done
if ! command -v jq >/dev/null 2>&1; then
    log_warn "未安装 jq — 将用 python3 解析 JSON（较慢）"
fi

# 0.2 服务连通性
check_http "C++ 服务 /api/system/health" "$CPP_URL/api/system/health" "200" || {
    echo -e "${C_RED}C++ 服务未启动！请先运行: ./start.sh${C_RST}"; exit 1;
}
check_http "Python 服务 /health" "$PY_URL/health" "200" || {
    echo -e "${C_RED}Python 服务未启动！请先运行: ./start.sh${C_RST}"; exit 1;
}

# 0.3 配置预检（关键：现场改 .env 后是否生效）
echo -e "\n${C_DIM}检查 Python 服务读到的实际配置：${C_RST}"
READY_JSON=$(curl -s -m 10 "$PY_URL/health/ready" 2>/dev/null)
echo "$READY_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  就绪状态 ready = {d.get('ready')}\")
checks = d.get('checks', {})
for k in ['cpp_backend', 'neo4j', 'llm']:
    c = checks.get(k, {})
    st = c.get('status', 'unknown')
    icon = '✓' if st in ('connected','available') else '⚠' if st in ('disconnected','unavailable') else '?'
    url = c.get('url', c.get('uri',''))
    print(f\"  {icon} {k:12} = {st}  {url}\")
" 2>/dev/null || log_warn "无法解析 /health/ready"

READY=$(echo "$READY_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ready'))" 2>/dev/null)
if [ "$READY" = "True" ]; then
    log_pass "就绪检查通过（ready=True）— 即使 LLM/Neo4j 不可用也判定就绪"
else
    log_warn "就绪检查未通过（ready=$READY）— 检查 C++ 后端是否正常"
fi

# 关键提醒：env 污染问题
echo
echo -e "${C_YEL}⚠ 现场提醒：${C_RST}如果改过 .env 但配置没生效，是因为 start.sh 的 'source .env'"
echo -e "  会把旧值导出为环境变量，优先级高于 .env 文件。解决：新开终端启动，或 unset LLM_* 后重启。"
echo -e "  本脚本检测到的 LLM 地址如下（应与你 .env 里的一致）："
LLM_STATUS=$(curl -s -m 5 "$PY_URL/api/llm/status" 2>/dev/null)
echo "$LLM_STATUS" | python3 -c "
import sys, json
d = json.load(sys.stdin)
tm = d.get('text_model', {})
print(f\"  文本模型: {tm.get('name')} @ {tm.get('base_url')} available={tm.get('available')}\")
vm = d.get('vision_model', {})
print(f\"  视觉模型: {vm.get('name')} @ {vm.get('base_url')} available={vm.get('available')}\")
" 2>/dev/null || log_warn "无法解析 /api/llm/status"

# ============================================================
# 阶段 1：创建真实分析任务并等待完成
# ============================================================
section "阶段 1：创建分析任务（llm_analyze=false，纯功能）"

# 智能判断：Android 逻辑提取（data 目录或 zip）vs 磁盘镜像
ANDROID_LOGICAL=false
case "$IMAGE_PATH" in
    *.zip|*/data|*/data/) ANDROID_LOGICAL=true;;
esac

if [ "$ANDROID_LOGICAL" = true ]; then
    log_warn "检测到 Android 逻辑提取数据，将用 --android-source 模式（非本脚本 HTTP 流程）"
    log_skip "HTTP 任务创建（Android 逻辑提取走命令行）"
    echo -e "  ${C_DIM}建议手动验证: ./build/forensic_analyzer \"$IMAGE_PATH\" --android-analyze --android-source dir${C_RST}"
    # 此处可扩展；脚本主要覆盖磁盘镜像 HTTP 流程
else
    # 创建任务
    TASK_BODY=$(cat <<EOF
{"image_path":"$(realpath "$IMAGE_PATH" 2>/dev/null || echo "$IMAGE_PATH")","scenarios":$SCEN_JSON,"llm_analyze":false,"priority":"normal"}
EOF
)
    echo -e "${C_DIM}请求体: $TASK_BODY${C_RST}"
    CREATE_RESP=$(curl -s -m 15 -X POST "$CPP_URL/api/tasks" \
        -H "Content-Type: application/json" -d "$TASK_BODY" 2>/dev/null)
    TASK_ID=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

    if [ -z "$TASK_ID" ] || [ "$TASK_ID" = "" ]; then
        log_fail "任务创建失败 — 响应: $CREATE_RESP"
        echo -e "${C_RED}无法继续。请检查镜像路径和 C++ 服务日志。${C_RST}"
        exit 1
    fi
    log_pass "任务创建成功: $TASK_ID"

    # 等待完成
    echo -e "\n${C_DIM}等待任务完成（超时 ${TASK_TIMEOUT}s，每 5s 轮询）...${C_RST}"
    ELAPSED=0
    FINAL_STATUS=""
    while [ $ELAPSED -lt $TASK_TIMEOUT ]; do
        STATUS_RESP=$(curl -s -m 10 "$CPP_URL/api/tasks/$TASK_ID" 2>/dev/null)
        FINAL_STATUS=$(echo "$STATUS_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
p = d.get('progress', {})
print(f\"{d.get('status','?')}|{p.get('overall_percentage',0)}%|{p.get('phase_description','')}\")
" 2>/dev/null || echo "?|0%|")

        # 进度显示（单行刷新，不污染日志）
        printf "\r  [${ELAPSED}s] %s                " "$FINAL_STATUS"

        case "$FINAL_STATUS" in
            completed*) printf "\r\033[K"; log_pass "任务完成: $FINAL_STATUS"; break;;
            failed*|error*|cancelled*) printf "\r\033[K"; log_fail "任务异常结束: $FINAL_STATUS"; break;;
        esac
        sleep 5
        ELAPSED=$((ELAPSED+5))
    done

    if [ $ELAPSED -ge $TASK_TIMEOUT ]; then
        printf "\r\033[K"
        log_fail "任务超时未完成（${TASK_TIMEOUT}s）"
        log_warn "任务可能仍在运行，可在前端查看: $TASK_ID"
    fi

    # 任务完成后给 DB 一点时间释放文件句柄（避免 SQLITE_BUSY 误报）
    # 实测：status=completed 后 DB 可能仍在 checkpoint，立即查询会拿到锁错误
    sleep 3
fi

# ============================================================
# 阶段 2：数据库产物验证（核心 — 证明真的抽出了数据）
# ============================================================
section "阶段 2：数据库产物验证"

if [ -z "$TASK_ID" ]; then
    log_skip "数据库验证（无任务 ID）"
else
    # 获取任务产物路径
    DBS_RESP=$(curl -s -m 10 "$CPP_URL/api/tasks/$TASK_ID/databases" 2>/dev/null)
    echo "$DBS_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for db in d.get('databases', []):
    print(f\"{db.get('type')}|{db.get('path')}\")
" 2>/dev/null > /tmp/onsite_dbs.txt

    while IFS='|' read -r dbtype dbpath; do
        [ -z "$dbpath" ] && continue
        if [ ! -f "$dbpath" ]; then
            log_fail "$dbtype.db 文件不存在: $dbpath"
            continue
        fi
        # 检查能否打开（带重试，应对任务刚完成时的 SQLITE_BUSY）
        DB_OK=false
        TABLES_OUT=""
        for attempt in 1 2 3; do
            TABLES_OUT=$(sqlite3 "$dbpath" ".tables" 2>/tmp/onsite_sqlite_err)
            if [ $? -eq 0 ]; then DB_OK=true; break; fi
            sleep 1
        done
        if [ "$DB_OK" = false ]; then
            log_fail "$dbtype.db 无法打开: $(cat /tmp/onsite_sqlite_err)"
            continue
        fi
        log_pass "$dbtype.db 可读: $(basename "$dbpath")"

        # 检查行数（raw/files 表是核心）
        case "$dbtype" in
            raw)
                ROWS=$(sqlite3 "$dbpath" "SELECT COUNT(*) FROM files;" 2>/dev/null || echo "ERR")
                if [ "$ROWS" = "ERR" ]; then
                    log_warn "$dbtype.db 无 files 表（镜像可能为空或格式不支持）"
                elif [ "$ROWS" -gt 0 ] 2>/dev/null; then
                    log_pass "raw.db files 表有 $ROWS 行（真实抽取成功）"
                    # ★ 多分区完整性检查（实战发现的关键问题）
                    # 症状：大镜像（>5G）只抽出极少文件（<2000），几乎肯定是只解析了 boot 分区
                    IMG_SIZE_BYTES=$(stat -c%s "$IMAGE_PATH" 2>/dev/null || echo 0)
                    IMG_SIZE_GB=$(( IMG_SIZE_BYTES / 1024 / 1024 / 1024 ))
                    if [ "$IMG_SIZE_GB" -ge 5 ] && [ "$ROWS" -lt 2000 ]; then
                        log_fail "⚠ 多分区数据丢失告警：镜像 ${IMG_SIZE_GB}GB 但只抽出 ${ROWS} 个文件"
                        echo -e "      ${C_YEL}这几乎肯定意味着只解析了第一个分区（boot/保留区），${C_RST}"
                        echo -e "      ${C_YEL}真实数据分区被跳过。Windows/Linux 专项数据可能全空。${C_RST}"
                        echo -e "      ${C_DIM}诊断：mmls${IMAGE_PATH##*.} 查看$IMAGE_PATH 的分区表${C_RST}"
                        echo -e "      ${C_DIM}详见 scripts/FINDINGS_MULTI_PARTITION.md${C_RST}"
                    fi
                else
                    log_fail "raw.db files 表为空（0 行）— 镜像解析失败？"
                fi
                ;;
            events)
                ROWS=$(sqlite3 "$dbpath" "SELECT COUNT(*) FROM events;" 2>/dev/null || echo "ERR")
                if [ "$ROWS" = "ERR" ]; then log_warn "events.db 无 events 表"
                elif [ "$ROWS" -gt 0 ] 2>/dev/null; then log_pass "events.db 有 $ROWS 条事件"
                else log_warn "events.db 事件为 0（镜像无时间戳元数据？）"; fi
                ;;
            files)
                # files.db 有多个分类表，统计总数
                TOTAL=$(sqlite3 "$dbpath" "
                    SELECT SUM(cnt) FROM (
                        SELECT COUNT(*) cnt FROM images UNION ALL
                        SELECT COUNT(*) FROM documents UNION ALL
                        SELECT COUNT(*) FROM executables UNION ALL
                        SELECT COUNT(*) FROM source_code UNION ALL
                        SELECT COUNT(*) FROM web_files UNION ALL
                        SELECT COUNT(*) FROM system_files UNION ALL
                        SELECT COUNT(*) FROM archives UNION ALL
                        SELECT COUNT(*) FROM databases UNION ALL
                        SELECT COUNT(*) FROM videos UNION ALL
                        SELECT COUNT(*) FROM audio_files UNION ALL
                        SELECT COUNT(*) FROM email_files UNION ALL
                        SELECT COUNT(*) FROM encrypted_files UNION ALL
                        SELECT COUNT(*) FROM unknown_files
                    );" 2>/dev/null || echo "ERR")
                if [ "$TOTAL" = "ERR" ]; then log_warn "files.db 分类表查询失败"
                elif [ "$TOTAL" -gt 0 ] 2>/dev/null; then log_pass "files.db 分类文件共 $TOTAL 个"
                else log_warn "files.db 分类为空"; fi
                ;;
            windows|linux|android|oss)
                ROWS=$(sqlite3 "$dbpath" "
                    SELECT SUM(cnt) FROM (
                        SELECT COUNT(*) cnt FROM sqlite_master WHERE type='table'
                    );" 2>/dev/null || echo "0")
                log_pass "$dbtype.db 存在（$ROWS 个表）"
                # 列出表名供人工查看
                echo -e "    ${C_DIM}表: $(sqlite3 "$dbpath" ".tables" 2>/dev/null | tr '\n' ' ')${C_RST}"
                # ★ 平台专项"全空表"告警（实战发现的关键问题）
                # 症状：表都建了但每张表 0 行——专项分析器初始化了但没拿到数据
                NONEMPTY=$(sqlite3 "$dbpath" "
                    SELECT COUNT(*) FROM (
                        SELECT 1 FROM sqlite_master WHERE type='table'
                        AND (SELECT COUNT(*) FROM pragma_table_info(name)) > 0
                    );" 2>/dev/null)
                TOTAL_ROWS=0
                for t in $(sqlite3 "$dbpath" ".tables" 2>/dev/null); do
                    c=$(sqlite3 "$dbpath" "SELECT COUNT(*) FROM \"$t\";" 2>/dev/null || echo 0)
                    TOTAL_ROWS=$((TOTAL_ROWS + c))
                done
                if [ "$TOTAL_ROWS" -eq 0 ]; then
                    log_fail "⚠ $dbtype.db 所有表全空（0 行数据）— 平台专项未抽到任何 artifact"
                    echo -e "      ${C_YEL}通常原因：多分区镜像只解析了 boot 分区，artifact 在未解析的分区里${C_RST}"
                    echo -e "      ${C_DIM}详见 scripts/FINDINGS_MULTI_PARTITION.md${C_RST}"
                else
                    log_pass "$dbtype.db 共有 $TOTAL_ROWS 行数据"
                fi
                ;;
        esac
        echo
    done < /tmp/onsite_dbs.txt
fi

# ============================================================
# 阶段 3：非 AI 功能验证（基于真实任务产物）
# ============================================================
section "阶段 3：非 AI 功能验证"

if [ -z "$TASK_ID" ]; then
    log_skip "功能验证（无任务 ID）"
else
    # 时间线
    check_http "时间线-综合视图" "$CPP_URL/api/forensics/timeline/comprehensive?task_id=$TASK_ID" "200"
    check_http "时间线-分布" "$CPP_URL/api/forensics/timeline/distribution?task_id=$TASK_ID" "200"

    # 统计
    check_http "统计-总览" "$CPP_URL/api/forensics/statistics/overview?task_id=$TASK_ID" "200"
    check_http "统计-文件分布" "$CPP_URL/api/forensics/statistics/file-distribution?task_id=$TASK_ID" "200"

    # 文件分类列表
    check_http "文件列表" "$CPP_URL/api/tasks/$TASK_ID/files" "200"

    # 导出（TOON / JSON）— 非 AI
    check_http "TOON 导出" "$CPP_URL/api/forensics/export/toon?task_id=$TASK_ID" "200"
    check_http "事件 JSON 导出" "$CPP_URL/api/forensics/export/events/json?task_id=$TASK_ID" "200"

    # Office 解析（Python，非 LLM）
    check_http "Office 解析服务" "$PY_URL/api/office/parse" "422" \
        --method POST --data '{}' \
        && log_pass "Office 端点存在（422=参数校验正常，非崩溃）"

    # 数据库查询代理（Python）
    check_http "数据库代理服务" "$PY_URL/api/db/tasks/$TASK_ID" "200"
fi

# 全文搜索（需先建索引，可选）
section "阶段 3.5：全文搜索（Xapian）"
if [ -n "$TASK_ID" ]; then
    # 搜索索引需要 source_path + index_path（POST body）
    EXTRACTION_DIR=$(curl -s -m 10 "$CPP_URL/api/tasks/$TASK_ID" 2>/dev/null | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('extraction_directory',''))" 2>/dev/null)
    if [ -z "$EXTRACTION_DIR" ] || [ ! -d "$EXTRACTION_DIR" ]; then
        log_warn "未找到抽取目录，跳过搜索索引测试"
    else
        IDX_BODY=$(cat <<EOF
{"source_path":"$EXTRACTION_DIR","index_path":"/tmp/onsite_xapian_idx","recursive":true}
EOF
)
        INDEX_RESP=$(curl -s -m 120 -o /dev/null -w "%{http_code}" -X POST \
            "$CPP_URL/api/search/index" -H "Content-Type: application/json" \
            -d "$IDX_BODY" 2>/dev/null || echo "000")
        if [ "$INDEX_RESP" = "200" ] || [ "$INDEX_RESP" = "201" ]; then
            log_pass "搜索索引建立 (HTTP $INDEX_RESP)"
            check_http "全文搜索" "$CPP_URL/api/search/fulltext?q=test&index=/tmp/onsite_xapian_idx" "200"
        else
            log_warn "搜索索引建立返回 $INDEX_RESP（可能耗时长或目录无文本内容）"
        fi
    fi
fi

# ============================================================
# 阶段 4：AI 降级行为验证（现场能测 AI 的唯一角度）
# ============================================================
section "阶段 4：AI 降级行为验证（不可用时应优雅，不应崩溃）"

echo -e "${C_DIM}此阶段验证：当 LLM 不可用时，系统是否优雅降级而非崩溃。${C_RST}"
echo -e "${C_DIM}现场 AI 必然不可用，所以这里期望的不是'AI 成功'，而是'失败得体'。${C_RST}\n"

# 4.1 LLM 状态端点（前端用它判断是否显示 AI 功能）
LLM_STATUS=$(curl -s -m 10 "$PY_URL/api/llm/status" 2>/dev/null)
LLM_AVAIL=$(echo "$LLM_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('text_model',{}).get('available','?'))" 2>/dev/null)
if [ "$LLM_AVAIL" = "False" ]; then
    log_pass "/api/llm/status 正确报告 LLM 不可用（前端可据此优雅提示）"
else
    log_warn "/api/llm/status 报告 LLM available=$LLM_AVAIL（现场若意外可用，AI 功能可实测）"
fi

# 4.2 就绪状态不应被 LLM 拖累
if [ "$READY" = "True" ]; then
    log_pass "LLM 不可用时 readiness 仍为 true（正确：LLM 是 optional）"
else
    log_fail "LLM 不可用导致 readiness=false（错误：应降级而非失败）"
fi

# 4.3 文件分析端点：应快速失败，不应卡死
if [ -n "$TASK_ID" ]; then
    DBS_RESP=$(curl -s -m 10 "$CPP_URL/api/tasks/$TASK_ID/databases" 2>/dev/null)
    FILES_DB=$(echo "$DBS_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for db in d.get('databases', []):
    if db.get('type') == 'files': print(db.get('path',''))
" 2>/dev/null | head -1)

    if [ -n "$FILES_DB" ]; then
        echo -e "${C_DIM}触发文件 LLM 分析（期望：快速失败，不卡死）...${C_RST}"
        T0=$(date +%s%N)
        ANALYZE_CODE=$(curl -s -m 30 -o /dev/null -w "%{http_code}" -X POST "$PY_URL/api/llm/analyze" \
            -H "Content-Type: application/json" \
            -d "{\"content\":\"onsite probe\",\"task_id\":\"$TASK_ID\"}" 2>/dev/null || echo "000")
        T1=$(date +%s%N)
        ELAPSED_MS=$(( (T1 - T0) / 1000000 ))
        # 期望：LLM 不可用 → 500 ConnectError；或参数问题 422。都不应卡死。
        if [ "$ELAPSED_MS" -lt 5000 ]; then
            if [ "$ANALYZE_CODE" = "500" ]; then
                log_pass "文件分析端点快速失败（HTTP 500, ${ELAPSED_MS}ms）— 不卡死 ✓"
            elif [ "$ANALYZE_CODE" = "422" ]; then
                log_warn "文件分析返回 422（参数校验，未触达 LLM）— 端点存活"
            else
                log_warn "文件分析返回 HTTP $ANALYZE_CODE（${ELAPSED_MS}ms）"
            fi
        else
            log_fail "文件分析卡死（${ELAPSED_MS}ms > 5s）— 这是现场前必须修的问题"
        fi
    fi

    # 4.4 Current report surface: the legacy Chain B writer is retired. Keep this
    # deployment smoke read-only so it does not require Report Evidence or an LLM.
    echo -e "${C_DIM}验证当前取证报告 API 已挂载（不触发生成）...${C_RST}"
    REPORT_CODE=$(curl -s -m 10 -o /dev/null -w "%{http_code}" \
        "$PY_URL/api/reports?scope_type=task&scope_id=$TASK_ID" 2>/dev/null || echo "000")
    if [ "$REPORT_CODE" = "200" ] || [ "$REPORT_CODE" = "404" ]; then
        log_pass "取证报告 API 已挂载（HTTP $REPORT_CODE；未触发生成）"
    else
        log_warn "取证报告 API 返回 HTTP $REPORT_CODE"
    fi

    # 4.5 知识图谱：Neo4j 不可用时应 disabled 而非崩溃
    GSTAT=$(curl -s -m 10 "$PY_URL/api/graphiti/status" 2>/dev/null)
    GST=$(echo "$GSTAT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null)
    if [ "$GST" = "disconnected" ] || [ "$GST" = "disabled" ]; then
        log_pass "知识图谱正确标记为 $GST（Neo4j 不可用，不崩溃）"
    else
        log_warn "知识图谱状态: $GST"
    fi
fi

# ============================================================
# 阶段 5：现场要采集的产物（带回本地回放 AI）
# ============================================================
section "阶段 5：现场产物采集清单（带回本地补测 AI）"

if [ -n "$TASK_ID" ]; then
    echo -e "${C_DIM}以下数据库是'喂给 AI 的原料'，带回本地后可启动 LLM 回放 AI 分析：${C_RST}\n"
    DBS_RESP=$(curl -s -m 10 "$CPP_URL/api/tasks/$TASK_ID/databases" 2>/dev/null)
    echo "$DBS_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for db in d.get('databases', []):
    p = db.get('path','')
    import os
    sz = os.path.getsize(p) if os.path.exists(p) else 0
    print(f\"  [{db.get('type'):8}] {p}  ({sz//1024} KB)\")
" 2>/dev/null
    echo
    echo -e "  ${C_BLD}打包命令：${C_RST}"
    echo -e "  ${C_CYA}tar czf onsite_task_${TASK_ID:0:8}.tar.gz \\"${C_RST}
    DBS_RESP=$(curl -s -m 10 "$CPP_URL/api/tasks/$TASK_ID/databases" 2>/dev/null)
    echo "$DBS_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
paths = [db.get('path','') for db in d.get('databases', []) if db.get('path')]
for p in paths:
    print('    ' + p + ' \\\\')
" 2>/dev/null
    echo
    echo -e "  ${C_DIM}带回后：使用 R2 Report Evidence + /api/reports/generate 显式生成报告${C_RST}"
fi

# ============================================================
# 清理
# ============================================================
if [ "$KEEP_TASK" = false ] && [ -n "$TASK_ID" ]; then
    section "清理"
    DEL_CODE=$(curl -s -m 10 -o /dev/null -w "%{http_code}" -X DELETE "$CPP_URL/api/tasks/$TASK_ID" 2>/dev/null || echo "000")
    if [ "$DEL_CODE" = "200" ] || [ "$DEL_CODE" = "204" ]; then
        log_pass "任务已清理: $TASK_ID"
    else
        log_warn "任务清理返回 $DEL_CODE（如需保留加 --keep-task）"
    fi
fi

# ============================================================
# 汇总
# ============================================================
section "测试汇总"
echo
echo -e "  ${C_GRN}通过 (PASS): $PASS${C_RST}"
echo -e "  ${C_RED}失败 (FAIL): $FAIL${C_RST}"
echo -e "  ${C_YEL}警告 (WARN): $WARN${C_RST}"
echo -e "  ${C_DIM}跳过 (SKIP): $SKIP${C_RST}"
echo
echo -e "  ${C_DIM}详细结果: $RESULTS_FILE${C_RST}"

if [ $FAIL -gt 0 ]; then
    echo
    echo -e "  ${C_RED}${C_BLD}有 $FAIL 项失败！${C_RST} ${C_RED}请检查上方 FAIL 项详情。${C_RST}"
    echo -e "  ${C_DIM}失败可能原因：镜像格式不支持 / 依赖缺失 / 服务未完全启动 / 代码 bug${C_RST}"
    exit 1
elif [ $WARN -gt 0 ]; then
    echo
    echo -e "  ${C_YEL}有 $WARN 项警告（非致命，但建议关注）。${C_RST}"
    exit 0
else
    echo
    echo -e "  ${C_GRN}${C_BLD}全部通过！系统在 AI 不可用情况下功能正常。${C_RST}"
    exit 0
fi
