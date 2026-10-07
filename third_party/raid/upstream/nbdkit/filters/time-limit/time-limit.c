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
#include <stdint.h>
#include <string.h>
#include <errno.h>
#include <sys/time.h>

#include <nbdkit-filter.h>

#include "tvdiff.h"

/* Time limit (0, 0 = filter is disabled). */
static unsigned secs = 60, nsecs = 0;
static int64_t usecs;

static int
time_limit_config (nbdkit_next_config *next, nbdkit_backend *nxdata,
                   const char *key, const char *value)
{
  if (strcmp (key, "time-limit") == 0 ||
      strcmp (key, "time_limit") == 0 ||
      strcmp (key, "timelimit") == 0) {
    if (nbdkit_parse_delay (key, value, &secs, &nsecs) == -1)
      return -1;
    return 0;
  }

  return next (nxdata, key, value);
}

static int
time_limit_config_complete (nbdkit_next_config_complete *next,
                            nbdkit_backend *nxdata)
{
  if (secs == 0 && nsecs == 0)
    usecs = 0;
  else
    usecs = secs * 1000000 + nsecs / 1000;
  if (usecs < 0) {
    nbdkit_error ("time limit cannot be negative");
    return -1;
  }

  return next (nxdata);
}

struct handle
{
  struct timeval start_t;
};

static void *
time_limit_open (nbdkit_next_open *next, nbdkit_context *nxdata,
                 int readonly, const char *exportname, int is_tls)
{
  struct handle *h;

  h = malloc (sizeof *h);
  if (h == NULL) {
    nbdkit_error ("malloc: %m");
    return NULL;
  }
  /* XXX To do: Start counting in preconnect. */
  gettimeofday (&h->start_t, NULL);

  if (next (nxdata, readonly, exportname) == -1)
    return NULL;

  return h;
}

static void
time_limit_close (void *handle)
{
  free (handle);
}

static int
check_time_limit (struct handle *h, int *err)
{
  if (usecs > 0) {
    struct timeval t;
    int64_t diff;

    gettimeofday (&t, NULL);
    diff = tvdiff_usec (&h->start_t, &t);

    if (diff > usecs) {
      nbdkit_debug ("time-limit: time limit exceeded, connection closed");

      /* Note this is not an error from the point of view of nbdkit,
       * but we need an error to send back to the client, although as
       * we are shutting the connection down asynchronously it won't
       * actually receive it.
       */
#ifdef ESHUTDOWN
      *err = ESHUTDOWN;
#else
      *err = EIO;
#endif
      nbdkit_disconnect (1);
      return -1;
    }
  }
  return 0;
}

static int
time_limit_pread (nbdkit_next *next,
                  void *handle, void *buf, uint32_t count, uint64_t offset,
                  uint32_t flags, int *err)
{
  if (check_time_limit (handle, err) == -1)
    return -1;
  return next->pread (next, buf, count, offset, flags, err);
}

static int
time_limit_pwrite (nbdkit_next *next,
                   void *handle,
                   const void *buf, uint32_t count, uint64_t offset,
                   uint32_t flags,
                   int *err)
{
  if (check_time_limit (handle, err) == -1)
    return -1;
  return next->pwrite (next, buf, count, offset, flags, err);
}

static int
time_limit_trim (nbdkit_next *next,
                 void *handle, uint32_t count, uint64_t offset, uint32_t flags,
                 int *err)
{
  if (check_time_limit (handle, err) == -1)
    return -1;
  return next->trim (next, count, offset, flags, err);
}

static int
time_limit_zero (nbdkit_next *next,
                 void *handle, uint32_t count, uint64_t offset, uint32_t flags,
                 int *err)
{
  if (check_time_limit (handle, err) == -1)
    return -1;
  return next->zero (next, count, offset, flags, err);
}

static int
time_limit_extents (nbdkit_next *next,
                    void *handle, uint32_t count, uint64_t offset,
                    uint32_t flags,
                    struct nbdkit_extents *extents, int *err)
{
  if (check_time_limit (handle, err) == -1)
    return -1;
  return next->extents (next, count, offset, flags, extents, err);
}

static int
time_limit_cache (nbdkit_next *next,
                  void *handle, uint32_t count, uint64_t offset, uint32_t flags,
                  int *err)
{
  if (check_time_limit (handle, err) == -1)
    return -1;
  return next->cache (next, count, offset, flags, err);
}

static struct nbdkit_filter filter = {
  .name              = "time-limit",
  .longname          = "nbdkit time limit filter",
  .config            = time_limit_config,
  .config_complete   = time_limit_config_complete,
  .open              = time_limit_open,
  .close             = time_limit_close,

  .pread             = time_limit_pread,
  .pwrite            = time_limit_pwrite,
  .trim              = time_limit_trim,
  .zero              = time_limit_zero,
  .extents           = time_limit_extents,
  .cache             = time_limit_cache,
};

NBDKIT_REGISTER_FILTER (filter)
