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

#include <config.h>

#include <string.h>

#include <lzma.h>

#include <nbdkit-filter.h>

#include "blkcache.h"
#include "lzipfile.h"

static uint64_t maxblock = 512 * 1024 * 1024;
static uint32_t maxdepth = 8;

static int
lzip_config (nbdkit_next_config *next, nbdkit_backend *nxdata,
             const char *key, const char *value)
{
  if (strcmp (key, "lzip-max-block") == 0) {
    int64_t r = nbdkit_parse_size (value);
    if (r == -1)
      return -1;
    maxblock = (uint64_t) r;
    return 0;
  }
  else if (strcmp (key, "lzip-max-depth") == 0) {
    if (nbdkit_parse_uint32_t ("lzip-max-depth", value, &maxdepth) == -1)
      return -1;
    if (maxdepth == 0) {
      nbdkit_error ("'lzip-max-depth' parameter must be >= 1");
      return -1;
    }
    return 0;
  }
  else
    return next (nxdata, key, value);
}

#define lzip_config_help \
  "lzip-max-block=<SIZE> (optional) Maximum block size allowed (default: 512M)\n"\
  "lzip-max-depth=<N>    (optional) Maximum blocks in cache (default: 8)\n"

/* The per-connection handle. */
struct lzip_handle {
  lzipfile *lz;

  /* Block cache. */
  blkcache *c;
};

/* Create the per-connection handle. */
static void *
lzip_open (nbdkit_next_open *next, nbdkit_context *nxdata,
           int readonly, const char *exportname, int is_tls)
{
  struct lzip_handle *h;

  /* Always pass readonly=1 to the underlying plugin. */
  if (next (nxdata, 1, exportname) == -1)
    return NULL;

  h = malloc (sizeof *h);
  if (h == NULL) {
    nbdkit_error ("malloc: %m");
    return NULL;
  }

  h->c = new_blkcache (maxdepth);
  if (!h->c) {
    free (h);
    return NULL;
  }

  /* Initialized in lz_prepare. */
  h->lz = NULL;

  return h;
}

/* Free up the per-connection handle. */
static void
lzip_close (void *handle)
{
  struct lzip_handle *h = handle;
  blkcache_stats stats;

  blkcache_get_stats (h->c, &stats);
  nbdkit_debug ("cache: hits = %zu, misses = %zu", stats.hits, stats.misses);

  lzipfile_close (h->lz);
  free_blkcache (h->c);
  free (h);
}

static int
lzip_prepare (nbdkit_next *next, void *handle,
              int readonly)
{
  struct lzip_handle *h = handle;

  h->lz = lzipfile_open (next);
  if (!h->lz)
    return -1;

  if (maxblock < lzipfile_max_uncompressed_block_size (h->lz)) {
    nbdkit_error ("lzip file largest block is bigger than lzip-max-block\n"
                  "Either recompress the lzip file with smaller blocks "
                  "(see nbdkit-lzip-filter(1))\n"
                  "or make lzip-max-block parameter bigger.\n"
                  "Current lzip-max-block = %" PRIu64 " (bytes)\n"
                  "Largest block in lzip file = %" PRIu64 " (bytes)",
                  maxblock,
                  lzipfile_max_uncompressed_block_size (h->lz));
    return -1;
  }

  return 0;
}

/* Description. */
static const char *
lzip_export_description (nbdkit_next *next,
                         void *handle)
{
  const char *base = next->export_description (next);

  if (!base)
    return NULL;
  return nbdkit_printf_intern ("expansion of lzip-compressed image: %s", base);
}

/* Get the file size. */
static int64_t
lzip_get_size (nbdkit_next *next, void *handle)
{
  struct lzip_handle *h = handle;

  return lzipfile_get_size (h->lz);
}

/* We need this because otherwise the layer below can_write is called
 * and that might return true (eg. if the plugin has a pwrite method
 * at all), resulting in writes being passed through to the layer
 * below.  This is possibly a bug in nbdkit.
 */
static int
lzip_can_write (nbdkit_next *next,
                void *handle)
{
  return 0;
}

/* Whatever the plugin says, this filter is consistent across connections. */
static int
lzip_can_multi_conn (nbdkit_next *next,
                     void *handle)
{
  return 1;
}

/* Similar to above. */
static int
lzip_can_extents (nbdkit_next *next,
                  void *handle)
{
  return 0;
}

/* Cache */
static int
lzip_can_cache (nbdkit_next *next,
                void *handle)
{
  /* We are already operating as a cache regardless of the plugin's
   * underlying .can_cache, but it's easiest to just rely on nbdkit's
   * behavior of calling .pread for caching.
   */
  return NBDKIT_CACHE_EMULATE;
}

/* Read data from the file. */
static int
lzip_pread (nbdkit_next *next,
            void *handle, void *buf, uint32_t count, uint64_t offset,
            uint32_t flags, int *err)
{
  struct lzip_handle *h = handle;
  char *data;
  uint64_t start, size;
  uint32_t n;

  /* Find the block in the cache. */
  data = get_block (h->c, offset, &start, &size);
  if (!data) {
    /* Not in the cache.  We need to read the block from the xz file. */
    data = lzipfile_read_block (h->lz, next, flags, err,
                                offset, &start, &size);
    if (data == NULL)
      return -1;
    put_block (h->c, start, size, data);
  }

  /* It's possible if the blocks are really small or oddly aligned or
   * if the requests are large that we need to read the following
   * block to satisfy the request.
   */
  n = count;
  if (start + size - offset < n)
    n = start + size - offset;

  memcpy (buf, &data[offset-start], n);
  buf += n;
  count -= n;
  offset += n;
  if (count > 0)
    return lzip_pread (next, h, buf, count, offset, flags, err);

  return 0;
}

static int lzip_thread_model (int next_thread_model)
{
  return NBDKIT_THREAD_MODEL_SERIALIZE_REQUESTS;
}

static struct nbdkit_filter filter = {
  .name               = "lzip",
  .longname           = "nbdkit lzip filter",
  .config             = lzip_config,
  .config_help        = lzip_config_help,
  .thread_model       = lzip_thread_model,
  .open               = lzip_open,
  .close              = lzip_close,
  .prepare            = lzip_prepare,
  .export_description = lzip_export_description,
  .get_size           = lzip_get_size,
  .can_write          = lzip_can_write,
  .can_extents        = lzip_can_extents,
  .can_cache          = lzip_can_cache,
  .can_multi_conn     = lzip_can_multi_conn,
  .pread              = lzip_pread,
};

NBDKIT_REGISTER_FILTER (filter)
