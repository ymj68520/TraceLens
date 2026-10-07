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

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

#include <nbdkit-filter.h>

#include "cleanup.h"
#include "vector.h"

/* Mapping of (readonly, is_tls, exportname) to context. */
static pthread_mutex_t export_list_lock = PTHREAD_MUTEX_INITIALIZER;
struct export_entry {
  int readonly, is_tls;
  char *exportname;
  nbdkit_next *context;
};
DEFINE_VECTOR_TYPE (export_list, struct export_entry);
static export_list exports;

static void
openonce_cleanup (nbdkit_backend *backend)
{
  size_t i;

  /* Free up the export list, close all the contexts. */
  for (i = 0; i < exports.len; ++i) {
    nbdkit_debug ("openonce: freeing context for export \"%s\"",
                  exports.ptr[i].exportname);
    free (exports.ptr[i].exportname);
    /* XXX Failure of this is technically data loss.  Hopefully
     * clients used flush or FUA earlier and weren't relying on this
     * to persist any final data.
     */
    exports.ptr[i].context->finalize (exports.ptr[i].context);
    nbdkit_next_context_close (exports.ptr[i].context);
  }
  export_list_reset (&exports);
}

/* Per-connection data. */
struct handle {
  nbdkit_next *next;
};

static void *
openonce_open (nbdkit_next_open *next, nbdkit_context *nxdata,
               int readonly, const char *exportname, int is_tls)
{
  struct handle *h;

  h = calloc (1, sizeof *h);
  if (h == NULL) {
    nbdkit_error ("calloc: %m");
    return NULL;
  }

  {
    ACQUIRE_LOCK_FOR_CURRENT_SCOPE (&export_list_lock);
    size_t i;

    /* Check if an existing (readonly, is_tls, exportname) entry exists. */
    for (i = 0; i < exports.len; ++i) {
      if (exports.ptr[i].readonly == readonly &&
          exports.ptr[i].is_tls == is_tls &&
          strcmp (exports.ptr[i].exportname, exportname) == 0) {
        nbdkit_debug ("openonce: reusing existing context for export \"%s\"",
                      exportname);
        h->next = exports.ptr[i].context;
        break;
      }
    }
    if (!h->next) {
      struct export_entry new_entry;

      new_entry.exportname = strdup (exportname);
      if (new_entry.exportname == NULL) {
        nbdkit_error ("strdup: %m");
        free (h);
        return NULL;
      }
      new_entry.readonly = readonly;
      new_entry.is_tls = is_tls;

      h->next = new_entry.context =
        nbdkit_next_context_open (nbdkit_context_get_backend (nxdata),
                                  readonly, exportname, /* shared= */ 1);
      if (new_entry.context == NULL) {
        free (new_entry.exportname);
        free (h);
        return NULL;
      }

      /* Open this new plugin context. */
      if (h->next->prepare (h->next) == -1) {
        h->next->finalize (h->next);
        free (new_entry.exportname);
        nbdkit_next_context_close (h->next);
        free (h);
        return NULL;
      }

      /* The new context is fully opened, so add to the list of exports. */
      if (export_list_append (&exports, new_entry) == -1) {
        free (new_entry.exportname);
        nbdkit_next_context_close (new_entry.context);
        free (h);
        return NULL;
      }

      nbdkit_debug ("openonce: allocated new context for export \"%s\"",
                    exportname);
    }
  }

  return h;
}

static void
openonce_close (void *handle)
{
  struct handle *h = handle;

  /* XXX A future enhancement here would be to allow plugins to be
   * closed when they have no clients open.  This would have to
   * settable by a flag.
   */

  free (h);
}

/* If the plugin advertises SERIALIZE_REQUESTS, then because we are
 * sharing the plugin across connections, we must tighten nbdkit's
 * thread model to SERIALIZE_ALL_REQUESTS, so that we don't call into
 * the plugin overlapped from multiple connections.  However other
 * models are fine to leave alone.
 */
static int
openonce_thead_model (int next_thread_model)
{
  switch (next_thread_model) {
  case NBDKIT_THREAD_MODEL_SERIALIZE_REQUESTS:
    return NBDKIT_THREAD_MODEL_SERIALIZE_ALL_REQUESTS;
  default:
    return next_thread_model;
  }
}

/* We have to adjust every possible callback so that it uses the
 * context from the handle (h->next) instead of the context passed to
 * us by nbdkit (which will be NULL).
 */

static int64_t
openonce_get_size (nbdkit_next *next, void *handle)
{
  struct handle *h = handle;
  return h->next->get_size (h->next);
}

static const char *
openonce_export_description (nbdkit_next *next, void *handle)
{
  struct handle *h = handle;
  return h->next->export_description (h->next);
}

static int
openonce_block_size (nbdkit_next *next, void *handle,
                     uint32_t *minimum, uint32_t *preferred, uint32_t *maximum)
{
  struct handle *h = handle;
  return h->next->block_size (h->next, minimum, preferred, maximum);
}

static int
openonce_can_write (nbdkit_next *next,
                    void *handle)
{
  struct handle *h = handle;
  return h->next->can_write (h->next);
}

static int
openonce_can_flush (nbdkit_next *next,
                    void *handle)
{
  struct handle *h = handle;
  return h->next->can_flush (h->next);
}

static int
openonce_is_rotational (nbdkit_next *next, void *handle)
{
  struct handle *h = handle;
  return h->next->is_rotational (h->next);
}

static int
openonce_can_trim (nbdkit_next *next,
                   void *handle)
{
  struct handle *h = handle;
  return h->next->can_trim (h->next);
}

static int
openonce_can_zero (nbdkit_next *next,
                   void *handle)
{
  struct handle *h = handle;
  return h->next->can_zero (h->next);
}

static int
openonce_can_fast_zero (nbdkit_next *next, void *handle)
{
  struct handle *h = handle;
  return h->next->can_fast_zero (h->next);
}

static int
openonce_can_extents (nbdkit_next *next,
                      void *handle)
{
  struct handle *h = handle;
  return h->next->can_extents (h->next);
}

static int
openonce_can_fua (nbdkit_next *next,
                  void *handle)
{
  struct handle *h = handle;
  return h->next->can_fua (h->next);
}

static int
openonce_can_multi_conn (nbdkit_next *next, void *handle)
{
  struct handle *h = handle;
  return h->next->can_multi_conn (h->next);
}

static int
openonce_can_cache (nbdkit_next *next,
                    void *handle)
{
  struct handle *h = handle;
  return h->next->can_cache (h->next);
}

static int
openonce_pread (nbdkit_next *next,
                void *handle, void *buf, uint32_t count, uint64_t offset,
                uint32_t flags, int *err)
{
  struct handle *h = handle;
  return h->next->pread (h->next, buf, count, offset, flags, err);
}

static int
openonce_pwrite (nbdkit_next *next,
                 void *handle,
                 const void *buf, uint32_t count, uint64_t offset,
                 uint32_t flags, int *err)
{
  struct handle *h = handle;
  return h->next->pwrite (h->next, buf, count, offset, flags, err);
}

static int
openonce_flush (nbdkit_next *next,
                void *handle, uint32_t flags, int *err)
{
  struct handle *h = handle;
  return h->next->flush (h->next, flags, err);
}

static int
openonce_trim (nbdkit_next *next,
               void *handle, uint32_t count, uint64_t offset, uint32_t flags,
               int *err)
{
  struct handle *h = handle;
  return h->next->trim (h->next, count, offset, flags, err);
}

static int
openonce_zero (nbdkit_next *next,
               void *handle, uint32_t count, uint64_t offset, uint32_t flags,
               int *err)
{
  struct handle *h = handle;
  return h->next->zero (h->next, count, offset, flags, err);
}

static int
openonce_extents (nbdkit_next *next,
                  void *handle, uint32_t count, uint64_t offset, uint32_t flags,
                  struct nbdkit_extents *extents, int *err)
{
  struct handle *h = handle;
  return h->next->extents (h->next, count, offset, flags, extents, err);
}

static int
openonce_cache (nbdkit_next *next,
                void *handle, uint32_t count, uint64_t offset, uint32_t flags,
                int *err)
{
  struct handle *h = handle;
  return h->next->cache (h->next, count, offset, flags, err);
}

static struct nbdkit_filter filter = {
  .name              = "openonce",
  .longname          = "nbdkit openonce filter",
  .cleanup           = openonce_cleanup,
  .thread_model      = openonce_thead_model,
  .open              = openonce_open,
  .close             = openonce_close,
  .get_size          = openonce_get_size,
  .export_description= openonce_export_description,
  .block_size        = openonce_block_size,
  .can_write         = openonce_can_write,
  .can_flush         = openonce_can_flush,
  .is_rotational     = openonce_is_rotational,
  .can_trim          = openonce_can_trim,
  .can_zero          = openonce_can_zero,
  .can_fast_zero     = openonce_can_fast_zero,
  .can_extents       = openonce_can_extents,
  .can_fua           = openonce_can_fua,
  .can_multi_conn    = openonce_can_multi_conn,
  .can_cache         = openonce_can_cache,
  .pread             = openonce_pread,
  .pwrite            = openonce_pwrite,
  .flush             = openonce_flush,
  .trim              = openonce_trim,
  .zero              = openonce_zero,
  .extents           = openonce_extents,
  .cache             = openonce_cache,
};

NBDKIT_REGISTER_FILTER (filter)
