#pragma once
#include <nlohmann/json.hpp>
#include <algorithm>

namespace forensics::selection {
inline nlohmann::json deliveryQuality(const nlohmann::json& plan) {
    using json = nlohmann::json;
    json counts={{"candidates",0},{"readable",0},{"zero_records",0},{"metadata_only",0},{"unsupported",0},{"parse_failed",0},{"unprobed",0}};
    for (const auto& item:plan.value("candidates",json::array())) {
        counts["candidates"]=counts["candidates"].get<int>()+1;
        const auto state=item.value("probe_state","unprobed");
        std::string bucket=state=="ok" || state=="readable" || state=="partial" ? "readable" : state=="metadata_only" ? "metadata_only" : state=="unsupported" ? "unsupported" : state=="error" || state=="source_error" ? "parse_failed" : state=="unprobed" ? "unprobed" : "";
        if(!bucket.empty()) counts[bucket]=counts[bucket].get<int>()+1;
        auto probe=item.value("probe",json::object());
        if(probe.is_object()) {
            auto coverage=probe.value("coverage",json::object());
            auto records=coverage.value("parsed_record_count",coverage.value("record_count",json(nullptr)));
            if(state=="ok" && records.is_number_integer() && records.get<long long>()==0 && !coverage.value("truncated",false)) counts["zero_records"]=counts["zero_records"].get<int>()+1;
        }
    }
    const auto execution=plan.value("execution",json::object());
    counts["model_failed"]=execution.value("failed",0);
    counts["unprocessed"]=std::max(0,plan.value("counts",json::object()).value("selected",0)-execution.value("completed",0)-execution.value("failed",0));
    return {{"status","limited"},{"label","有范围限制"},{"counts",counts},
        {"scope","当前选择计划的探测与执行计数；未选择不等于无关，签名识别不等于解析成功"}};
}
}
