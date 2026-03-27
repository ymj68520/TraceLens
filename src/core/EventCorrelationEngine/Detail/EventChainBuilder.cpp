#include "../EventCorrelationEngine.h"
#include "AuditLog/AuditLog.h"
#include <algorithm>
#include <chrono>
#include <map>
#include <queue>
#include <set>
#include <sstream>

namespace EventCorrelationEngine {

std::vector<EventChain> EventCorrelationEngine::analyzeEventChains() {
    AuditLog::instance().log("SYSTEM", "EVENT_CHAIN_ANALYSIS_START", "Starting event chain analysis");

    buildEventChains();

    // 保存事件链到数据库
    for (const auto& chain : eventChains_) {
        insertEventChain(chain);
    }

    AuditLog::instance().log("SYSTEM", "EVENT_CHAIN_ANALYSIS_COMPLETE", "Event chain analysis completed. Found " + std::to_string(eventChains_.size()) + " event chains");
    return eventChains_;
}

std::shared_ptr<EventChainNode> EventCorrelationEngine::buildEventChainNode(int64_t eventId) {
    auto eventInfo = getEventInfo(eventId);
    if (eventInfo.empty()) {
        return nullptr;
    }

    auto node = std::make_shared<EventChainNode>();
    node->eventId = eventId;
    node->eventType = eventInfo["event_type"];
    node->timestamp = std::stoll(eventInfo["timestamp"]);
    node->description = eventInfo["description"];
    node->path = eventInfo["file_path"];
    node->confidence = 1.0;

    return node;
}

void EventCorrelationEngine::buildEventChains() {
    eventChains_.clear();

    // 基于关联构建事件链
    std::map<int64_t, std::vector<EventCorrelation>> eventCorrelations;
    for (const auto& corr : correlations_) {
        eventCorrelations[corr.eventId1].push_back(corr);
        eventCorrelations[corr.eventId2].push_back(corr);
    }

    // 构建事件链
    std::set<int64_t> processedEvents;
    for (const auto& [eventId, corrs] : eventCorrelations) {
        if (processedEvents.count(eventId)) {
            continue;
        }

        // 构建事件链
        EventChain chain;
        chain.chainId = "chain_" + std::to_string(std::chrono::system_clock::now().time_since_epoch().count());
        chain.confidence = 0.0;

        // 广度优先搜索构建链条
        std::queue<int64_t> eventQueue;
        eventQueue.push(eventId);
        processedEvents.insert(eventId);

        std::map<int64_t, std::shared_ptr<EventChainNode>> nodeMap;

        while (!eventQueue.empty()) {
            int64_t currentEventId = eventQueue.front();
            eventQueue.pop();

            auto node = buildEventChainNode(currentEventId);
            if (!node) {
                continue;
            }

            nodeMap[currentEventId] = node;
            chain.nodes.push_back(node);

            // 查找相关事件
            for (const auto& corr : eventCorrelations[currentEventId]) {
                int64_t relatedEventId = (corr.eventId1 == currentEventId) ? corr.eventId2 : corr.eventId1;
                if (!processedEvents.count(relatedEventId)) {
                    eventQueue.push(relatedEventId);
                    processedEvents.insert(relatedEventId);

                    // 添加父子关系
                    auto relatedNode = buildEventChainNode(relatedEventId);
                    if (relatedNode) {
                        nodeMap[relatedEventId] = relatedNode;
                        if (corr.direction == CorrelationDirection::UNI) {
                            if (corr.eventId1 == currentEventId) {
                                node->children.push_back(relatedNode);
                                relatedNode->parents.push_back(node);
                            } else {
                                node->parents.push_back(relatedNode);
                                relatedNode->children.push_back(node);
                            }
                        } else {
                            node->children.push_back(relatedNode);
                            node->parents.push_back(relatedNode);
                            relatedNode->children.push_back(node);
                            relatedNode->parents.push_back(node);
                        }
                    }
                }
            }
        }

        // 设置根节点和时间范围
        if (!chain.nodes.empty()) {
            // 选择最早的事件作为根节点
            chain.root = *std::min_element(chain.nodes.begin(), chain.nodes.end(),
                [](const std::shared_ptr<EventChainNode>& a, const std::shared_ptr<EventChainNode>& b) {
                    return a->timestamp < b->timestamp;
                });

            // 计算时间范围
            chain.startTime = chain.root->timestamp;
            chain.endTime = chain.root->timestamp;
            for (const auto& node : chain.nodes) {
                chain.startTime = std::min(chain.startTime, node->timestamp);
                chain.endTime = std::max(chain.endTime, node->timestamp);
            }

            // 计算链条置信度
            double totalConfidence = 0.0;
            for (const auto& node : chain.nodes) {
                totalConfidence += node->confidence;
            }
            chain.confidence = totalConfidence / chain.nodes.size();

            // 生成描述
            std::stringstream desc;
            desc << "Event chain with " << chain.nodes.size() << " events";
            chain.description = desc.str();

            // 提取涉及的实体
            std::set<std::string> entities;
            for (const auto& node : chain.nodes) {
                if (!node->path.empty()) {
                    entities.insert(node->path);
                }
            }
            chain.involvedEntities.assign(entities.begin(), entities.end());

            eventChains_.push_back(chain);
        }
    }
}

std::vector<CausalRelationship> EventCorrelationEngine::discoverCausalRelationships() {
    AuditLog::instance().log("SYSTEM", "CAUSAL_RELATIONSHIP_DISCOVERY_START", "Starting causal relationship discovery");

    analyzeCausalRelationships();

    // 保存因果关系到数据库
    for (const auto& relationship : causalRelationships_) {
        insertCausalRelationship(relationship);
    }

    AuditLog::instance().log("SYSTEM", "CAUSAL_RELATIONSHIP_DISCOVERY_COMPLETE", "Causal relationship discovery completed. Found " + std::to_string(causalRelationships_.size()) + " causal relationships");
    return causalRelationships_;
}

void EventCorrelationEngine::analyzeCausalRelationships() {
    causalRelationships_.clear();

    // 基于关联和时间顺序分析因果关系
    for (const auto& corr : correlations_) {
        // 只考虑单向关联和有时间顺序的关联
        if (corr.direction == CorrelationDirection::UNI || corr.eventId1 < corr.eventId2) {
            auto event1Info = getEventInfo(corr.eventId1);
            auto event2Info = getEventInfo(corr.eventId2);

            if (event1Info.empty() || event2Info.empty()) {
                continue;
            }

            int64_t time1 = std::stoll(event1Info["timestamp"]);
            int64_t time2 = std::stoll(event2Info["timestamp"]);

            // 确保时间顺序
            if (time1 < time2) {
                // 计算因果置信度
                double causalConfidence = corr.confidence * 0.9; // 因果置信度略低于关联置信度

                // 检查是否符合因果模式
                std::string mechanism = "";
                if (corr.correlationType == "sequence") {
                    mechanism = "Temporal sequence";
                } else if (corr.correlationType == "same_file") {
                    mechanism = "Same file interaction";
                } else if (corr.correlationType == "same_source") {
                    mechanism = "Same source action";
                }

                if (!mechanism.empty() && causalConfidence > 0.7) {
                    CausalRelationship rel;
                    rel.causeEventId = corr.eventId1;
                    rel.effectEventId = corr.eventId2;
                    rel.confidence = causalConfidence;
                    rel.description = "Cause: " + event1Info["event_type"] + ", Effect: " + event2Info["event_type"];
                    rel.timeDelay = time2 - time1;
                    rel.mechanism = mechanism;

                    causalRelationships_.push_back(rel);
                }
            }
        }
    }
}

} // namespace EventCorrelationEngine
