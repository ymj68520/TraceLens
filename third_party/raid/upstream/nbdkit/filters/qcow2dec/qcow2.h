/* nbdkit
 * Copyright Red Hat
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met:
 *
 * * Redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer.
 *
 * * Redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution.
 *
 * * Neither the name of Red Hat nor the names of its contributors may be
 * used to endorse or promote products derived from this software without
 * specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY RED HAT AND CONTRIBUTORS ''AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
 * THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
 * PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL RED HAT OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
 * USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
 * OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 */

#ifndef NBDKIT_QCOW2_H
#define NBDKIT_QCOW2_H

#include <stdint.h>

struct qcow2_header {
  uint32_t magic;
  uint32_t version;
  uint64_t backing_file_offset;
  uint32_t backing_file_size;
  uint32_t cluster_bits;
  uint64_t size; /* in bytes */
  uint32_t crypt_method;
  uint32_t l1_size;
  uint64_t l1_table_offset;
  uint64_t refcount_table_offset;
  uint32_t refcount_table_clusters;
  uint32_t nb_snapshots;
  uint64_t snapshots_offset;

  /* The following fields are only valid for version >= 3 */
  uint64_t incompatible_features;
  uint64_t compatible_features;
  uint64_t autoclear_features;
  uint32_t refcount_order;
  uint32_t header_length;

  /* Additional fields */
  uint8_t compression_type;

  /* Header must be a multiple of 8 */
  uint8_t padding[7];
} __attribute__((packed));

#define QCOW2_MAGIC_STRING "QFI\xfb"

#define QCOW2_INCOMPAT_FEAT_DIRTY_BIT              0
#define QCOW2_INCOMPAT_FEAT_CORRUPT_BIT            1
#define QCOW2_INCOMPAT_FEAT_EXTERNAL_DATA_FILE_BIT 2
#define QCOW2_INCOMPAT_FEAT_COMPRESSION_TYPE_BIT   3
#define QCOW2_INCOMPAT_FEAT_EXTENDED_L2_BIT        4

#define QCOW2_COMPAT_FEAT_LAZY_REFCOUNTS_BIT       0

#define QCOW2_AUTOCLEAR_FEAT_BITMAPS_BIT           0
#define QCOW2_AUTOCLEAR_FEAT_RAW_EXTERNAL_BIT      1

#define QCOW2_L1_ENTRY_RESERVED_MASK ((UINT64_C(127) << 56) | 511)
#define QCOW2_L1_ENTRY_OFFSET_MASK   (~((UINT64_C(255) << 56) | 511))

#define QCOW2_L2_ENTRY_RESERVED_MASK ((UINT64_C(63) << 56) | 510)
#define QCOW2_L2_ENTRY_OFFSET_MASK   (~((UINT64_C(255) << 56) | 511))
#define QCOW2_L2_ENTRY_TYPE_MASK     (UINT64_C(1) << 62)

#endif /* NBDKIT_QCOW2_H */
