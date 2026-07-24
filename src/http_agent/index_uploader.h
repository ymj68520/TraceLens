#pragma once

// Uploads a batch of locally-indexed disk-image METADATA to the server's
// POST /api/clients/{client_id}/index-images endpoint (client-auth, Task 9).
// Uses an injected IHttpClient so it is unit-tested with a FakeHttpClient — no
// live server, same pattern as ResultUploader.
//
// METADATA ONLY: the request body is a bare JSON array of DiskImageCreate
// objects ({path, size_bytes, format, image_metadata}); no image content or
// bytes are ever sent (see image_indexer.h). The server's index_disk_images
// takes `images: List[DiskImageCreate]`, so the body is the array itself, not a
// wrapper object.

#include "http_client.h"
#include "image_indexer.h"

#include <string>
#include <utility>
#include <vector>

namespace tracelens {

class IndexUploader {
public:
    IndexUploader(IHttpClient& client, std::string client_id)
        : client_(client), client_id_(std::move(client_id)) {}

    // POSTs the entries as a JSON array to
    // /api/clients/{client_id}/index-images. Returns true on a 2xx response.
    // An empty `entries` is a no-op success (nothing to report -> no round
    // trip). An empty client_id returns false with an error (the path cannot be
    // formed); callers treat indexing as best-effort and log+continue.
    bool upload(const std::vector<DiskImageEntry>& entries, std::string& out_error);

private:
    IHttpClient& client_;
    std::string client_id_;
};

}  // namespace tracelens
