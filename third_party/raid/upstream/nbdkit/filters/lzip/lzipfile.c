/* nbdkit lzip filter
 * Copyright Jan Felix Langenbach
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

/* liblzma is a complex interface, so abstract it here. */

#include <config.h>

#include <inttypes.h>
#include <stdbool.h>
#include <string.h>

#include <nbdkit-filter.h>

#include <lzma.h>

#include "byte-swapping.h"
#include "lzipindex.h"
#include "minmax.h"

#include "lzipfile.h"

#define BUFFER_SIZE ((size_t) 1024 * 1024)

#define LZIP_HEADER_SIZE       6
#define LZIP_FOOTER_SIZE       20
#define LZIP_HEADER_MAGIC      "LZIP\x01"
#define LZIP_HEADER_MAGIC_LEN  5

struct lzipfile {
  struct lzip_index idx;
  uint64_t max_uncompressed_block_size;
};

static bool check_header_magic (nbdkit_next *next, uint64_t offset);
static bool setup_index (nbdkit_next *next, lzip_index *idx);
static uint64_t get_max_uncompressed_block_size (lzip_index const *idx);

lzipfile *
lzipfile_open (nbdkit_next *next)
{
  lzipfile *lz;
  uint64_t size;

  lz = malloc (sizeof *lz);
  if (lz == NULL) {
    nbdkit_error ("malloc %m");
    return NULL;
  }

  /* Check file magic. */
  if (!check_header_magic (next, 0)) {
    nbdkit_error ("lzip: not an lzip file");
    goto err1;
  }

  /* Read and parse the indexes. */
  if (!setup_index (next, &lz->idx))
    goto err1;

  lz->max_uncompressed_block_size = get_max_uncompressed_block_size (&lz->idx);

  size = lz->idx.combined_data_size;
  nbdkit_debug ("lzip: size %" PRIu64 " bytes (%.1fM)",
                size, size / 1024.0 / 1024.0);
  nbdkit_debug ("lzip: %zu members", lz->idx.members.len);
  nbdkit_debug ("lzip: maximum uncompressed block size %" PRIu64 " bytes (%.1fM)",
                lz->max_uncompressed_block_size,
                lz->max_uncompressed_block_size / 1024.0 / 1024.0);
  nbdkit_debug ("lzip: indexable block size %" PRIu64 " bytes (%.1fM)",
                lz->idx.indexable_data_size,
                lz->idx.indexable_data_size / 1024.0 / 1024.0);

  return lz;

 err1:
  free (lz);
  return NULL;
}

static bool
check_header_magic (nbdkit_next *next, uint64_t offset)
{
  char buf[LZIP_HEADER_MAGIC_LEN];
  int err;

  if (next->get_size (next) < (LZIP_HEADER_SIZE + LZIP_FOOTER_SIZE)) {
    nbdkit_error ("lzip: file too short");
    return false;
  }
  if (next->pread (next, buf, LZIP_HEADER_MAGIC_LEN, offset, 0, &err) == -1) {
    nbdkit_error ("lzip: could not read header magic: error %d", err);
    return false;
  }
  if (memcmp (buf, LZIP_HEADER_MAGIC, LZIP_HEADER_MAGIC_LEN) != 0)
    return false;
  return true;
}

static bool
setup_index (nbdkit_next *next, lzip_index *idx)
{
  uint64_t pos, file_size, member_size, data_size;
  int err;
  uint8_t footer[LZIP_FOOTER_SIZE];
  lzip_index_member member;

  *idx = (lzip_index) {};

  file_size = next->get_size (next);
  if (file_size == -1) {
    nbdkit_error ("lzip: get_size: %m");
    goto err;
  }

  pos = file_size;

  while (pos > 0) {
    nbdkit_debug ("lzip: looping through members: pos = %" PRIu64, pos);

    if (pos < (LZIP_HEADER_SIZE + LZIP_FOOTER_SIZE)) {
      nbdkit_error ("lzip: corrupted file at %" PRIu64, pos);
      goto err;
    }

    if (next->pread (next, footer, LZIP_FOOTER_SIZE,
                     pos - LZIP_FOOTER_SIZE, 0, &err) == -1) {
      nbdkit_error ("lzip: read member footer: error %d", err);
      goto err;
    }

    nbdkit_debug ("lzip: decode member footer at pos = %" PRIu64, pos);

    memcpy (&data_size, &footer[4], sizeof (data_size));
    data_size = le64toh (data_size);

    memcpy (&member_size, &footer[12], sizeof (member_size));
    member_size = le64toh (member_size);

    nbdkit_debug ("lzip: member_size = %" PRIu64, member_size);

    if (member_size < (LZIP_HEADER_SIZE + LZIP_FOOTER_SIZE)) {
      nbdkit_error ("lzip: invalid member size (too small)");
      goto err;
    }

    if (member_size > pos) {
      nbdkit_error ("lzip: invalid member size (too big)");
      goto err;
    }

    pos -= member_size;

    nbdkit_debug ("lzip: decode member header at pos = %" PRIu64, pos);

    if (!check_header_magic (next, pos)) {
      nbdkit_error ("lzip: invalid member header");
      goto err;
    }

    member.member_offset = pos;
    member.member_size = member_size;
    member.data_size = data_size;

    if (lzip_index_prepend (idx, &member) == -1) {
      nbdkit_error ("lzip: allocation failure while growing index");
      goto err;
    }
  }

  lzip_index_finalize (idx);
  return true;

 err:
  lzip_index_destroy (idx);
  return false;
}

static uint64_t
get_max_uncompressed_block_size (lzip_index const *idx)
{
  uint64_t size = 0;

  if (idx->indexable_data_size) {
    return idx->indexable_data_size;
  }

  for (size_t i = 0; i < idx->members.len; ++i) {
    size = MAX (size, idx->members.ptr[i].data_size);
  }

  return size;
}

void
lzipfile_close (lzipfile *lz)
{
  if (lz) {
    lzip_index_destroy (&lz->idx);
    free (lz);
  }
}

uint64_t
lzipfile_max_uncompressed_block_size (lzipfile *lz)
{
  return lz->max_uncompressed_block_size;
}

uint64_t
lzipfile_get_size (lzipfile *lz)
{
  return lz->idx.combined_data_size;
}

char *
lzipfile_read_block (lzipfile *lz,
                     nbdkit_next *next,
                     uint32_t flags, int *err,
                     uint64_t offset,
                     uint64_t *start_rtn, uint64_t *size_rtn)
{
  lzip_index_member const *member = NULL;
  lzma_stream strm = LZMA_STREAM_INIT;
  lzma_ret ret = LZMA_OK;
  uint64_t pos = 0;
  char *buffer = NULL;
  char *data = NULL;

  if (!(member = lzip_index_search (&lz->idx, offset))) {
    nbdkit_error ("lzip: cannot find offset %" PRIu64 " in the lzip file", offset);
    return NULL;
  }

  *start_rtn = member->data_offset;
  *size_rtn = member->data_size;

  nbdkit_debug ("seek: member %td at file offset %" PRIu64,
                member - lz->idx.members.ptr, member->data_offset);

  ret = lzma_lzip_decoder (&strm, UINT64_MAX, 0);
  if (ret != LZMA_OK) {
    nbdkit_error ("lzip: could not initialize decoder (error %d)", ret);
    goto err;
  }

  data = malloc (member->data_size);
  if (data == NULL) {
    nbdkit_error ("malloc (%" PRIu64" bytes): %m\n"
                  "NOTE: If this error occurs, you may need to recompress "
                  "your lzip files with a smaller block size.",
                  member->data_size);
    goto err;
  }

  buffer = malloc (BUFFER_SIZE);
  if (buffer == NULL) {
    nbdkit_error ("malloc: %m");
    goto err;
  }

  strm.next_in = NULL;
  strm.avail_in = 0;
  strm.next_out = (uint8_t *) data;
  strm.avail_out = member->data_size;

  do {
    if (strm.avail_in == 0) {
      strm.avail_in = BUFFER_SIZE;

      if (pos + strm.avail_in > member->member_size) {
        strm.avail_in = member->member_size - pos;
      }

      if (strm.avail_in > 0) {
        strm.next_in = (uint8_t *) buffer;
        if (next->pread (next, buffer, strm.avail_in, member->member_offset + pos, 0, err) == -1) {
          nbdkit_error ("lzip: read: error %d", *err);
          goto err;
        }

        pos += strm.avail_in;
      }
    }

    ret = lzma_code (&strm, LZMA_RUN);
  } while (ret == LZMA_OK);

  if (ret != LZMA_OK && ret != LZMA_STREAM_END) {
    nbdkit_error ("lzip: could not decompress member (error %d)", ret);
    goto err;
  }

  lzma_end (&strm);
  free (buffer);
  return data;

 err:
  lzma_end (&strm);
  free (buffer);
  free (data);
  return NULL;
}
