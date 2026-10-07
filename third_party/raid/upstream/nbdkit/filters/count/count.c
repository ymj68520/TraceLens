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
#include <inttypes.h>

#include <nbdkit-filter.h>

#ifdef HAVE_STDATOMIC_H
#include <stdatomic.h>
#else
/* Only used for counting statistics. */
#define _Atomic /**/
#endif

static _Atomic uint64_t bytes_read, bytes_written, bytes_zeroed, bytes_trimmed;

static void
count_unload (void)
{
  nbdkit_debug ("count bytes: "
                "read %" PRIu64 ", "
                "written %" PRIu64 ", "
                "zeroed %" PRIu64 ", "
                "trimmed %" PRIu64,
                bytes_read, bytes_written, bytes_zeroed, bytes_trimmed);
}

/* Read data. */
static int
count_pread (nbdkit_next *next,
             void *handle,
             void *buf,
             uint32_t count, uint64_t offset, uint32_t flags,
             int *err)
{
  int r;

  r = next->pread (next, buf, count, offset, flags, err);
  if (r >= 0)
    bytes_read += count;
  return r;
}

/* Write data. */
static int
count_pwrite (nbdkit_next *next,
              void *handle,
              const void *buf,
              uint32_t count, uint64_t offset, uint32_t flags,
              int *err)
{
  int r;

  r = next->pwrite (next, buf, count, offset, flags, err);
  if (r >= 0)
    bytes_written += count;
  return r;
}

/* Trim data. */
static int
count_trim (nbdkit_next *next,
            void *handle, uint32_t count, uint64_t offset, uint32_t flags,
            int *err)
{
  int r;

  r = next->trim (next, count, offset, flags, err);
  if (r >= 0)
    bytes_trimmed += count;
  return r;
}

/* Zero data. */
static int
count_zero (nbdkit_next *next,
            void *handle, uint32_t count, uint64_t offset, uint32_t flags,
            int *err)
{
  int r;

  r = next->zero (next, count, offset, flags, err);
  if (r >= 0)
    bytes_zeroed += count;
  return r;
}

static struct nbdkit_filter filter = {
  .name              = "count",
  .longname          = "nbdkit count filter",
  .unload            = count_unload,
  .pread             = count_pread,
  .pwrite            = count_pwrite,
  .trim              = count_trim,
  .zero              = count_zero,
};

NBDKIT_REGISTER_FILTER (filter)
