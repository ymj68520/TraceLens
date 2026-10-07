/* nbdkit lzip index
 * Copyright Jan Felix Langenbach
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

#ifndef NBDKIT_LZIPINDEX_H
#define NBDKIT_LZIPINDEX_H

#include <stdint.h>
#include <stdio.h>

#include "vector.h"

/**
 * Holds the position information of one archive member.
 *
 * The fields `data_offset` and `data_size` refer to the section of the
 * uncompressed file that is contained in this archive member. The fields
 * `member_offset` and `member_size` refer to the section of the compressed file
 * that contains this archive member.
 *
 * When constructing an index, the field `data_offset` can be left blank. It is
 * initialized later by `lzip_index_finalize()`.
 */
typedef struct lzip_index_member {
  /** The starting address of the data block in the uncompressed file. */
  uint64_t data_offset;
  /** The size of the data block in the uncompressed file. */
  uint64_t data_size;
  /** The starting address of this archive member in the compressed file. */
  uint64_t member_offset;
  /** The size of this archive member in the compressed file. */
  uint64_t member_size;
} lzip_index_member;

DEFINE_VECTOR_TYPE (lzip_index_members, lzip_index_member);

/**
 * Index structure for a multimember lzip archive.
 *
 * When an archive consist of **lots of small members**, this index allows
 * random access to the compressed data. The standard `lzip` utility **does not
 * do this**! If you want random access, compress your files with `plzip`. If
 * you want file-level access to a compressed `tar` archive, use `tarlz`.
 *
 * An empty index can be created by zero-initialization. Members can then be
 * added in reverse order using `lzip_index_prepend()`. When the entire archive
 * has been read, `lzip_index_finalize()` should be called.
 *
 * Archive members can be searched by `lzip_index_search()`, allowing random
 * access to the compressed data. This is however **only possible** when the
 * archive consists of lots of small members
 *
 * The `members` array is allocated using `realloc()`. Before the index goes out
 * of scope, call `lzip_index_destroy()` to free those resources.
 */
typedef struct lzip_index {
  /** The size of the uncompressed file. */
  uint64_t combined_data_size;
  /**
   * The size of each uncompressed block, or zero.
   *
   * When this is non-zero, all uncompressed data blocks except the last are
   * guaranteed to have this size. In this case `lzip_index_search()` takes
   * only constant time.
   *
   * When this is zero, the uncompressed data blocks differ in size so
   * constant time searching is not possible. In this case
   * `lzip_index_search()` does a binary search in logarithmic time.
   */
  uint64_t indexable_data_size;
  /** The list of archive members in reverse order. */
  lzip_index_members members;
} lzip_index;

/**
 * Adds `member` to `index`.
 *
 * While reading an archive, the archive members should be added to `index` in
 * reverse. For each `member`, the fields `data_size`, `member_offset` and
 * `member_size` should be set to their respective values. The field
 * `data_offset` can be left blank, it is later computed by
 * `lzip_index_finalize()`.
 *
 * @return Zero on success, non-zero on allocation failure.
 */
int lzip_index_prepend (struct lzip_index *index, struct lzip_index_member const *member);

/**
 * Completes the initialization of `index`.
 *
 * This function goes through `index` and computes the `combined_data_size`
 * field, the `indexable_data_size` field and each member’s `data_offset` field.
 *
 * This function should be called as the last step when creating an index, after
 * all archive members have been added.
 */
void lzip_index_finalize (struct lzip_index *index);

/**
 * Finds the archive member holding the data at `data_offset`.
 *
 * The parameter `data_offset` is an offset into the uncompressed file. This
 * function searches for the archive member that holds the data at
 * `data_offset`. On success, it returns a pointer to a `struct
 * lzip_index_member` instance corresponding to the archive member. On failure,
 * it returns the null pointer.
 *
 * When `index->indexable_data_size` is non-zero, all uncompressed data blocks
 * except the last are guaranteed to have the same size. In that case, the
 * search takes only constant time. Otherwise, this function does a binary
 * search in logarithmic time.
 *
 * @param index The index to search.
 * @param data_offset The offset in the uncompressed file to search for.
 * @return The position of the archive member, or NULL.
 */
struct lzip_index_member const *
lzip_index_search (struct lzip_index const *index, uint64_t data_offset);

/** Frees the internal resources of `index`. */
void lzip_index_destroy (struct lzip_index *index);

#endif /* NBDKIT_LZIPINDEX_H */
