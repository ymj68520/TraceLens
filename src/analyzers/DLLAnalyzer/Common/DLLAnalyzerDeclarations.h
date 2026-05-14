// DLLAnalyzerDeclarations.h
// 前向声明和类前置声明

#pragma once
#ifndef DLL_ANALYZER_DECLARATIONS_H
#define DLL_ANALYZER_DECLARATIONS_H

#include "DLLDataTypes.h"

namespace forensics {
namespace dll {

// 前向声明
class PEParser;
class ELFParser;
class PEAnalyzer;
class AnomalyDetector;
class DependencyAnalyzer;

} // namespace dll
} // namespace forensics

#endif // DLL_ANALYZER_DECLARATIONS_H
