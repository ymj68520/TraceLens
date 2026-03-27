#include "../EventCorrelationEngine.h"
#include <fstream>
#include <sstream>
#include <functional>

namespace EventCorrelationEngine {

std::vector<EventCorrelation> EventCorrelationEngine::getCorrelations() const {
    return correlations_;
}

std::vector<EventChain> EventCorrelationEngine::getEventChains() const {
    return eventChains_;
}

std::vector<CausalRelationship> EventCorrelationEngine::getCausalRelationships() const {
    return causalRelationships_;
}

bool EventCorrelationEngine::exportCorrelations(const std::string& outputPath) const {
    // 导出关联分析结果到JSON文件
    std::ofstream output(outputPath);
    if (!output.is_open()) {
        return false;
    }

    output << "{" << std::endl;
    output << "  \"correlations\": [" << std::endl;

    for (size_t i = 0; i < correlations_.size(); ++i) {
        const auto& corr = correlations_[i];
        output << "    {" << std::endl;
        output << "      \"eventId1\": " << corr.eventId1 << "," << std::endl;
        output << "      \"eventId2\": " << corr.eventId2 << "," << std::endl;
        output << "      \"correlationType\": \"" << corr.correlationType << "\"," << std::endl;
        output << "      \"confidence\": " << corr.confidence << "," << std::endl;
        output << "      \"description\": \"" << corr.description << "\"," << std::endl;
        output << "      \"strength\": \"" << static_cast<int>(corr.strength) << "\"," << std::endl;
        output << "      \"direction\": \"" << static_cast<int>(corr.direction) << "\"," << std::endl;
        output << "      \"timestamp\": " << corr.timestamp << "," << std::endl;
        output << "      \"ruleId\": \"" << corr.ruleId << "\"" << std::endl;
        output << "    }" << (i < correlations_.size() - 1 ? "," : "") << std::endl;
    }

    output << "  ]" << std::endl;
    output << "}" << std::endl;

    output.close();
    return true;
}

bool EventCorrelationEngine::exportEventChains(const std::string& outputPath) const {
    // 导出事件链到JSON文件
    std::ofstream output(outputPath);
    if (!output.is_open()) {
        return false;
    }

    output << "{" << std::endl;
    output << "  \"eventChains\": [" << std::endl;

    for (size_t i = 0; i < eventChains_.size(); ++i) {
        const auto& chain = eventChains_[i];
        output << "    {" << std::endl;
        output << "      \"chainId\": \"" << chain.chainId << "\"," << std::endl;
        output << "      \"confidence\": " << chain.confidence << "," << std::endl;
        output << "      \"description\": \"" << chain.description << "\"," << std::endl;
        output << "      \"startTime\": " << chain.startTime << "," << std::endl;
        output << "      \"endTime\": " << chain.endTime << "," << std::endl;
        output << "      \"involvedEntities\": [";
        for (size_t j = 0; j < chain.involvedEntities.size(); ++j) {
            output << "\"" << chain.involvedEntities[j] << "\"" << (j < chain.involvedEntities.size() - 1 ? "," : "");
        }
        output << "]" << std::endl;
        output << "    }" << (i < eventChains_.size() - 1 ? "," : "") << std::endl;
    }

    output << "  ]" << std::endl;
    output << "}" << std::endl;

    output.close();
    return true;
}

bool EventCorrelationEngine::exportCausalRelationships(const std::string& outputPath) const {
    // 导出因果关系到JSON文件
    std::ofstream output(outputPath);
    if (!output.is_open()) {
        return false;
    }

    output << "{" << std::endl;
    output << "  \"causalRelationships\": [" << std::endl;

    for (size_t i = 0; i < causalRelationships_.size(); ++i) {
        const auto& rel = causalRelationships_[i];
        output << "    {" << std::endl;
        output << "      \"causeEventId\": " << rel.causeEventId << "," << std::endl;
        output << "      \"effectEventId\": " << rel.effectEventId << "," << std::endl;
        output << "      \"confidence\": " << rel.confidence << "," << std::endl;
        output << "      \"description\": \"" << rel.description << "\"," << std::endl;
        output << "      \"timeDelay\": " << rel.timeDelay << "," << std::endl;
        output << "      \"mechanism\": \"" << rel.mechanism << "\"" << std::endl;
        output << "    }" << (i < causalRelationships_.size() - 1 ? "," : "") << std::endl;
    }

    output << "  ]" << std::endl;
    output << "}" << std::endl;

    output.close();
    return true;
}

std::string EventCorrelationEngine::visualizeCorrelations() const {
    // 生成DOT格式的可视化
    std::stringstream dot;
    dot << "digraph EventCorrelations {" << std::endl;
    dot << "  rankdir=LR;" << std::endl;
    dot << "  node [shape=box, style=filled, fillcolor=lightblue];" << std::endl;

    for (const auto& corr : correlations_) {
        dot << "  event" << corr.eventId1 << " -> event" << corr.eventId2 << " [";
        dot << "label=\"" << corr.correlationType << " (" << corr.confidence << ")\", ";

        // 根据强度设置颜色
        switch (corr.strength) {
            case CorrelationStrength::LOW:
                dot << "color=green";
                break;
            case CorrelationStrength::MEDIUM:
                dot << "color=yellow";
                break;
            case CorrelationStrength::HIGH:
                dot << "color=orange";
                break;
            case CorrelationStrength::CRITICAL:
                dot << "color=red";
                break;
        }

        dot << "];" << std::endl;
    }

    dot << "}" << std::endl;
    return dot.str();
}

std::string EventCorrelationEngine::visualizeEventChains() const {
    // 生成DOT格式的可视化
    std::stringstream dot;
    dot << "digraph EventChains {" << std::endl;
    dot << "  rankdir=TB;" << std::endl;
    dot << "  node [shape=box, style=filled, fillcolor=lightgreen];" << std::endl;

    for (const auto& chain : eventChains_) {
        // 为每个事件链创建子图
        dot << "  subgraph cluster_" << chain.chainId << " {" << std::endl;
        dot << "    label=\"" << chain.description << " (Confidence: " << chain.confidence << ")\"" << std::endl;

        // 递归添加节点和边
        std::function<void(const std::shared_ptr<EventChainNode>&)> addNode = [&](const std::shared_ptr<EventChainNode>& node) {
            dot << "    event" << node->eventId << " [label=\"" << node->eventType << "\\n" << node->description << "\"];" << std::endl;
            for (const auto& child : node->children) {
                dot << "    event" << node->eventId << " -> event" << child->eventId << ";" << std::endl;
                addNode(child);
            }
        };

        if (chain.root) {
            addNode(chain.root);
        }

        dot << "  }" << std::endl;
    }

    dot << "}" << std::endl;
    return dot.str();
}

std::string EventCorrelationEngine::visualizeCausalRelationships() const {
    // 生成DOT格式的可视化
    std::stringstream dot;
    dot << "digraph CausalRelationships {" << std::endl;
    dot << "  rankdir=LR;" << std::endl;
    dot << "  node [shape=box, style=filled, fillcolor=lightyellow];" << std::endl;

    for (const auto& rel : causalRelationships_) {
        dot << "  event" << rel.causeEventId << " -> event" << rel.effectEventId << " [";
        dot << "label=\"" << rel.mechanism << " (" << rel.confidence << ")\", ";
        dot << "color=red, style=dashed";
        dot << "];" << std::endl;
    }

    dot << "}" << std::endl;
    return dot.str();
}

} // namespace EventCorrelationEngine
