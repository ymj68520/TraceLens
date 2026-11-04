/**
 * @file BinaryPlist.h
 * @brief Minimal reader for Apple binary property lists (bplist00).
 *
 * Manifest.plist in a real iOS backup is a binary plist, not XML. Parsing it
 * with an XML regex silently yields empty device identity and a false
 * "not encrypted" verdict, so the extractor needs a real reader.
 *
 * Scope is deliberately narrow: only what Manifest.plist needs, that is
 * dictionaries, arrays, strings, integers, booleans and dates. No writing,
 * no object graphs beyond the declared reference table, and every offset is
 * bounds-checked so a malformed evidence file cannot read out of range.
 */

#pragma once
#ifndef TRACELENS_BINARY_PLIST_H
#define TRACELENS_BINARY_PLIST_H

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace plist {

class Value;
using ValuePtr = std::shared_ptr<Value>;

/** A parsed plist value. Only the kind that was set is meaningful. */
class Value {
public:
    enum class Kind { Null, Boolean, Integer, Real, String, Date, Array, Dictionary };

    Kind kind = Kind::Null;
    bool boolean = false;
    long long integer = 0;
    double real = 0.0;
    std::string text;          // String, and the raw bytes for Date
    std::vector<ValuePtr> array;
    std::map<std::string, ValuePtr> dictionary;

    bool isDictionary() const { return kind == Kind::Dictionary; }
    bool isArray() const { return kind == Kind::Array; }
    bool isBoolean() const { return kind == Kind::Boolean; }
    bool isString() const { return kind == Kind::String; }

    /** Dictionary lookup; returns nullptr when absent or not a dict. */
    ValuePtr get(const std::string& key) const;

    /** Convenience accessors that return defaults instead of throwing. */
    std::string stringOr(const std::string& key, const std::string& fallback = "") const;
    long long integerOr(const std::string& key, long long fallback = 0) const;
    bool booleanOr(const std::string& key, bool fallback = false) const;
};

/**
 * @brief Parse a binary plist from memory.
 * @return The root value, or nullptr when `bytes` is not a valid bplist00.
 */
ValuePtr parseBinaryPlist(const std::string& bytes);

/**
 * @brief Parse a plist file, accepting both binary and XML encodings.
 * @param error Optional out-parameter describing the failure.
 */
ValuePtr parsePlistFile(const std::string& path, std::string* error = nullptr);

/** True when the buffer starts with Apple's binary plist magic. */
bool looksBinary(const std::string& bytes);

}  // namespace plist

#endif  // TRACELENS_BINARY_PLIST_H
