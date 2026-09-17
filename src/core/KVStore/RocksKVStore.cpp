// RocksKVStore.cpp
// RocksDB-backed KVStore implementation (mvp-phase1-acceptance SPEC §8, R1).

#include "RocksKVStore.h"

#include <rocksdb/options.h>
#include <rocksdb/write_batch.h>

#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <stdexcept>

namespace forensics::kv {

namespace {

std::runtime_error status_error(const std::string& what, const rocksdb::Status& s) {
    return std::runtime_error(what + ": " + s.ToString());
}

}  // namespace

RocksKVStore::RocksKVStore(const std::string& path,
                           const std::vector<std::string>& column_families) {
    // RocksDB does not create missing parent directories; the Python store
    // (rocksdb_store.ensure_parent) does the same thing.
    std::error_code fs_error;
    std::filesystem::create_directories(
        std::filesystem::path(path).parent_path(), fs_error);
    (void)fs_error;
    // Merge the requested families with whatever already exists on disk so a
    // reopen never leaves a family unopened (RocksDB refuses to open a DB
    // while some of its column families are missing from the request).
    std::vector<std::string> names;
    const auto list_status =
        rocksdb::DB::ListColumnFamilies(rocksdb::DBOptions(), path, &names);
    if (!list_status.ok()) {
        names.clear();  // fresh database: nothing on disk yet
    }
    const auto ensure = [&names](const std::string& cf) {
        if (std::find(names.begin(), names.end(), cf) == names.end()) {
            names.push_back(cf);
        }
    };
    ensure(rocksdb::kDefaultColumnFamilyName);
    ensure(kMetaCF);
    for (const auto& cf : column_families) ensure(cf);

    rocksdb::Options options;
    options.create_if_missing = true;
    options.create_missing_column_families = true;

    std::vector<rocksdb::ColumnFamilyDescriptor> descriptors;
    descriptors.reserve(names.size());
    for (const auto& name : names) {
        descriptors.emplace_back(name, rocksdb::ColumnFamilyOptions());
    }

    std::vector<rocksdb::ColumnFamilyHandle*> handles;
    rocksdb::DB* raw = nullptr;
    const auto status = rocksdb::DB::Open(options, path, descriptors, &handles, &raw);
    if (!status.ok()) {
        throw status_error("RocksKVStore: open " + path, status);
    }
    db_ = raw;
    cf_names_ = names;
    cf_handles_ = std::move(handles);
}

RocksKVStore::~RocksKVStore() {
    if (db_ == nullptr) return;
    for (auto* handle : cf_handles_) {
        if (handle) db_->DestroyColumnFamilyHandle(handle);
    }
    const auto status = db_->Close();
    if (!status.ok()) {
        std::fprintf(stderr, "RocksKVStore: close failed: %s\n",
                     status.ToString().c_str());
    }
    delete db_;
    db_ = nullptr;
}

rocksdb::ColumnFamilyHandle* RocksKVStore::handle_or_throw(const std::string& cf) const {
    const auto it = std::find(cf_names_.begin(), cf_names_.end(), cf);
    if (it == cf_names_.end()) {
        throw std::out_of_range("unknown column family: " + cf);
    }
    return cf_handles_[static_cast<size_t>(std::distance(cf_names_.begin(), it))];
}

void RocksKVStore::put(const std::string& cf, const std::string& key,
                       const std::string& value) {
    const auto status =
        db_->Put(rocksdb::WriteOptions(), handle_or_throw(cf), key, value);
    if (!status.ok()) throw status_error("put", status);
}

void RocksKVStore::erase(const std::string& cf, const std::string& key) {
    const auto status =
        db_->Delete(rocksdb::WriteOptions(), handle_or_throw(cf), key);
    if (!status.ok()) throw status_error("erase", status);
}

std::optional<std::string> RocksKVStore::get(const std::string& cf,
                                             const std::string& key) {
    std::string value;
    const auto status =
        db_->Get(rocksdb::ReadOptions(), handle_or_throw(cf), key, &value);
    if (status.IsNotFound()) return std::nullopt;
    if (!status.ok()) throw status_error("get", status);
    return value;
}

void RocksKVStore::write_batch(const std::vector<KVBatchOp>& ops) {
    rocksdb::WriteBatch batch;
    for (const auto& op : ops) {
        auto* handle = handle_or_throw(op.cf);
        const auto status = op.erase ? batch.Delete(handle, op.key)
                                     : batch.Put(handle, op.key, op.value);
        if (!status.ok()) throw status_error("write_batch stage", status);
    }
    const auto status = db_->Write(rocksdb::WriteOptions(), &batch);
    if (!status.ok()) throw status_error("write_batch commit", status);
}

std::vector<KVPair> RocksKVStore::scan_prefix(const std::string& cf,
                                              const std::string& prefix) {
    std::vector<KVPair> out;
    rocksdb::Iterator* it = db_->NewIterator(rocksdb::ReadOptions(), handle_or_throw(cf));
    for (it->Seek(prefix); it->Valid(); it->Next()) {
        if (!it->key().starts_with(prefix)) break;
        out.push_back({it->key().ToString(), it->value().ToString()});
    }
    const auto status = it->status();
    delete it;
    if (!status.ok()) throw status_error("scan_prefix", status);
    return out;
}

std::uint64_t RocksKVStore::count_prefix(const std::string& cf,
                                         const std::string& prefix) {
    return scan_prefix(cf, prefix).size();
}

void RocksKVStore::flush() {
    for (auto* handle : cf_handles_) {
        if (handle) {
            const auto status = db_->Flush(rocksdb::FlushOptions(), handle);
            if (!status.ok()) throw status_error("flush", status);
        }
    }
}

}  // namespace forensics::kv
