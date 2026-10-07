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
#include <string.h>
#include <math.h>
#include <assert.h>
#include <pthread.h>

#include <nbdkit-filter.h>

#include "cleanup.h"
#include "vector.h"

/* Arbitrarily chosen "track size" (in bytes).  If a seek is smaller
 * than this then we don't insert any delay.
 */
#define TRACK_SIZE (128*1024)

/* -D spinning.verbose=1 for extra debugging. */
NBDKIT_DLL_PUBLIC int spinning_debug_verbose = 0;

static unsigned nr_heads = 1;
static int separate_heads = 0;
static double min_seek_time = 0.01;
static double half_seek_time = 0.2;
static double max_seek_time = 0.5;

/* Quadratic equation: seek time = a.x^2 + b.x + c */
static double a, b, c;

static double
seek_time (double x)
{
  return a * x * x + b * x + c;
}

/* Parse seek times using nbdkit_parse_delay, but convert it back to a
 * double for curve calculations.
 */
static int
parse_seek_time (const char *what, const char *str, double *r)
{
  unsigned sec, nsec;

  if (nbdkit_parse_delay (what, str, &sec, &nsec) == -1)
    return -1;

  *r = sec + nsec / 1000000000.;
  return 0;
}

static int
spinning_config (nbdkit_next_config *next, nbdkit_backend *nxdata,
                 const char *key, const char *value)
{
  int r;

  if (strcmp (key, "heads") == 0) {
    r = nbdkit_parse_unsigned ("heads", value, &nr_heads);
    if (r == -1)
      return -1;
    if (nr_heads == 0 || nr_heads > 64) {
      nbdkit_error ("heads must be in the range [1..64] (was: %u)", nr_heads);
      return -1;
    }
    return 0;
  }
  else if (strcmp (key, "separate-heads") == 0) {
    r = nbdkit_parse_bool (value);
    if (r == -1)
      return -1;
    separate_heads = r;
    return 0;
  }
  else if (strcmp (key, "min-seek-time") == 0) {
    if (parse_seek_time (key, value, &min_seek_time) == -1)
      return -1;
    return 0;
  }
  else if (strcmp (key, "half-seek-time") == 0) {
    if (parse_seek_time (key, value, &half_seek_time) == -1)
      return -1;
    return 0;
  }
  else if (strcmp (key, "max-seek-time") == 0) {
    if (parse_seek_time (key, value, &max_seek_time) == -1)
      return -1;
    return 0;
  }

  else
    return next (nxdata, key, value);
}

static int
spinning_config_complete (nbdkit_next_config_complete *next,
                          nbdkit_backend *nxdata)
{
  /* Derive the factors of the quadratic equation a.x^2 + b.x + c
   * through the three known points:
   *
   * (x_1, y_1) = (0, min_seek_time)
   * (x_2, y_2) = (0.5, half_seek_time)
   * (x_3, y_3) = (1.0, max_seek_time)
   *
   * We don't need to do anything fancy here (Lagrange interpolation)
   * because the x's are "nice".  Instead it's just:
   *
   * y_1 = a.x_1^2 + b.x_1 + c
   * y_2 = a.x_2^2 + b.x_2 + c
   * y_3 = a.x_3^2 + b.x_3 + c
   *
   * Solving gives:
   *
   * y_1 = a.x_1^2 + b.x_1 + c
   * => y_1 = c
   * => c = min_seek_time
   *
   * y_2 = a.x_2^2 + b.x_2 + c
   * => half_seek_time = a/4 + b/2 + min_seek_time
   * => b/2 = half_seek_time - min_seek_time - a/4
   *
   * y_3 = a.x_3^2 + b.x_3 + c
   * => y_3 = a + b + min_seek_time
   * => y_3 = a + 2.(half_seek_time - min_seek_time - a/4) + min_seek_time
   * => y_3 = a + 2.half_seek_time - 2.min_seek_time - a/2 + min_seek_time
   * => y_3 = a/2 + 2.half_seek_time - min_seek_time
   * => a/2 = y_3 - 2.half_seek_time + min_seek_time
   * => a/2 = max_seek_time - 2.half_seek_time + min_seek_time
   *
   * Note that we don't constrain seek times to be sensible, eg. you
   * can have a track-to-track seek time which is larger than seeking
   * across the whole disk if you really want.
   */
  a = 2*(max_seek_time - 2*half_seek_time + min_seek_time);
  b = 2*(half_seek_time - min_seek_time - a/4);
  c = min_seek_time;

  nbdkit_debug ("spinning: [min, half, max] = %g, %g, %g",
                min_seek_time, half_seek_time, max_seek_time);
  nbdkit_debug ("spinning: quadratic curve: %g x^2 + %g x + %g",
                a, b, c);

  /* Check the quadratic is stable. */
  if (fabs (seek_time (0) - min_seek_time) >= 0.0005 ||
      fabs (seek_time (0.5) - half_seek_time) >= 0.0005 ||
      fabs (seek_time (1) - max_seek_time) >= 0.0005) {
    nbdkit_error ("in the spinning filter, seek time quadratic is not stable, "
                  "try using different {min,half,max}-seek-time parameters "
                  "and/or enable debugging and look at the quadratic curve");
    return -1;
  }

  return next (nxdata);
}

#define spinning_config_help \
  "heads=N                 Set the number of heads (default: 1)\n" \
  "separate-heads=BOOL     Use separate heads (default: false)\n" \
  "min-seek-time=N         Set track-to-track seek time (default: 0.01)\n" \
  "half-seek-time=N        Set half disk seek time (default: 0.2)\n" \
  "max-seek-time=N         Set whole disk seek time (default: 0.5)"

static int
spinning_is_rotational (nbdkit_next *next, void *handle)
{
  /* It's supposed to look like a real spinning disk! */
  return 1;
}

static int
spinning_can_multi_conn (nbdkit_next *next, void *handle)
{
  /* At present each NBD connection sees its own set of heads and
   * delays.  There should be a single view of heads across all NBD
   * clients.  For now work around this by disabling multi-conn.  XXX
   */
  return 0;
}

/* Current position and other data associated with each head. */
struct head {
  size_t n;                     /* Head number. */
  pthread_mutex_t lock;         /* Locked while seeking. */
  uint64_t pos;                 /* Current head position. */
  uint64_t start, end;          /* First offset and last offset + 1 */
};

DEFINE_VECTOR_TYPE(heads_vector, struct head);

/* Per-handle data. */
struct handle {
  uint64_t size;                /* Export size. */
  heads_vector heads;           /* List of heads. */
};

/* Open a connection. */
static void *
spinning_open (nbdkit_next_open *next, nbdkit_context *nxdata,
               int readonly, const char *exportname, int is_tls)
{
  struct handle *h;

  if (next (nxdata, readonly, exportname) == -1)
    return NULL;

  h = calloc (1, sizeof *h); /* h is populated during prepare() */
  if (h == NULL) {
    nbdkit_error ("calloc: %m");
    return NULL;
  }

  return h;
}

static void
spinning_close (void *handle)
{
  struct handle *h = handle;
  size_t i;

  for (i = 0; i < h->heads.len; ++i)
    pthread_mutex_destroy (&h->heads.ptr[i].lock);
  heads_vector_reset (&h->heads);
  free (h);
}

static int
spinning_prepare (nbdkit_next *next,
                  void *handle, int readonly)
{
  struct handle *h = handle;
  int64_t r;
  size_t i;
  uint64_t start, step;

  /* Get the size of the underlying export. */
  r = next->get_size (next);
  if (r == -1)
    return -1;
  h->size = r;

  if (heads_vector_reserve (&h->heads, nr_heads) == -1) {
    nbdkit_error ("calloc: %m");
    return -1;
  }
  h->heads.len = nr_heads;

  /* Split the disk across heads.  It can be that the disk is too
   * small for multiple heads, in which case we reduce h->heads.len
   * (even down to zero for a zero-sized disk).
   */
  if (h->size < h->heads.len)
    h->heads.len = h->size;

  nbdkit_debug ("spinning: heads %zu", h->heads.len);

  if (h->heads.len == 0)
    ;
  else if (h->heads.len == 1) {
    h->heads.ptr[0].start = 0;
    h->heads.ptr[0].end = h->size;
  }
  else {
    start = 0;
    step = h->size / h->heads.len;
    for (i = 0; i < h->heads.len; ++i) {
      h->heads.ptr[i].start = start;
      start += step;
      if (start > h->size)
        start = h->size;
      h->heads.ptr[i].end = start; /* start of the next head's range */
      if (i == h->heads.len-1)
        h->heads.ptr[i].end = h->size;
      nbdkit_debug ("spinning: head %zu: "
                    "[%" PRIu64 "-%" PRIu64 "] (%" PRIu64 " bytes)",
                    i, h->heads.ptr[i].start, h->heads.ptr[i].end-1,
                    h->heads.ptr[i].end - h->heads.ptr[i].start);
      assert (h->heads.ptr[i].end > h->heads.ptr[i].start);
    }
  }

  for (i = 0; i < h->heads.len; ++i) {
    h->heads.ptr[i].n = i;
    /* All heads start at the beginning of their range. */
    h->heads.ptr[i].pos = h->heads.ptr[i].start;
    /* Lock used while seeking or modifying the .pos field. */
    pthread_mutex_init (&h->heads.ptr[i].lock, NULL);
  }

  return 0;
}

static int
find_range (const void *vpos, const struct head *hd)
{
  const uint64_t pos = *(uint64_t *)vpos;

  if (pos < hd->start) return -1;
  if (pos >= hd->end) return 1;
  return 0;
}

static void
do_seek (struct handle *h, uint64_t new_pos)
{
  size_t i;
  struct head *head, *head_to_lock;
  int64_t delta;
  uint64_t o;

  /* Find which head is responsible for this part of the disk. */
  head = heads_vector_search (&h->heads, &new_pos, find_range);
  assert (head->start <= new_pos && new_pos < head->end);

  /* Offset of new_pos relative to the start of this head's range. */
  o = new_pos - head->start;

  /* If !separate_heads, we simulate the single arm by taking all
   * locks on the zeroth head.
   */
  head_to_lock = separate_heads ? head : &h->heads.ptr[0];
  ACQUIRE_LOCK_FOR_CURRENT_SCOPE (&head_to_lock->lock);

  /* How far must we move this head? */
  delta = head->pos - new_pos;
  if (delta < 0) delta = -delta;

  if (spinning_debug_verbose)
    nbdkit_debug ("spinning: do_seek: delta=%" PRIi64, delta);

  /* Move the head(s). */
  if (separate_heads) {
    /* Move only this head to its new position. */
    head->pos = new_pos;
    if (spinning_debug_verbose)
      nbdkit_debug ("spinning: do_seek: move head %zu to %" PRIu64,
                    head->n, head->pos);
  } else {
    /* Set all heads to the same offset from the start of their range. */
    for (i = 0; i < h->heads.len; ++i) {
      h->heads.ptr[i].pos = h->heads.ptr[i].start + o;
      if (spinning_debug_verbose)
        nbdkit_debug ("spinning: do_seek: move head %zu to %" PRIu64,
                      i, h->heads.ptr[i].pos);
    }
  }

  /* If we're moving more than a "track" distance then we must insert
   * a seek delay while holding the lock.
   */
  if (delta > TRACK_SIZE) {
    double stroke, t;

    stroke = delta / (double)(head->end - head->start);
    t = seek_time (stroke);
    if (spinning_debug_verbose)
      nbdkit_debug ("spinning: do_seek: stroke %g => delay %g", stroke, t);

    if (t >= 0) {
      unsigned sec, nsec;

      sec = floor (t);
      nsec = (t - sec) * 1000000000;
      if (spinning_debug_verbose)
        nbdkit_debug ("spinning: do_seek: sleeping for (%u, %u)", sec, nsec);
      nbdkit_nanosleep (sec, nsec);
    }
  }
}

/* Read data. */
static int
spinning_pread (nbdkit_next *next,
                void *handle, void *buf, uint32_t count, uint64_t offset,
                uint32_t flags, int *err)
{
  struct handle *h = handle;

  do_seek (h, offset);
  return next->pread (next, buf, count, offset, flags, err);
}

/* Write data. */
static int
spinning_pwrite (nbdkit_next *next,
                 void *handle, const void *buf, uint32_t count, uint64_t offset,
                 uint32_t flags, int *err)
{
  struct handle *h = handle;

  do_seek (h, offset);
  return next->pwrite (next, buf, count, offset, flags, err);
}

/* Zero data. */
static int
spinning_zero (nbdkit_next *next,
               void *handle, uint32_t count, uint64_t offset, uint32_t flags,
               int *err)
{
  struct handle *h = handle;

  do_seek (h, offset);
  return next->zero (next, count, offset, flags, err);
}

static struct nbdkit_filter filter = {
  .name              = "spinning",
  .longname          = "nbdkit spinning filter",
  .config            = spinning_config,
  .config_complete   = spinning_config_complete,
  .config_help       = spinning_config_help,
  .is_rotational     = spinning_is_rotational,
  .can_multi_conn    = spinning_can_multi_conn,
  .open              = spinning_open,
  .close             = spinning_close,
  .prepare           = spinning_prepare,
  .pread             = spinning_pread,
  .pwrite            = spinning_pwrite,
  .zero              = spinning_zero,
};

NBDKIT_REGISTER_FILTER (filter)
