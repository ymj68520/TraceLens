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
#include <unistd.h>
#include <pthread.h>

#if !defined(HAVE_STDATOMIC_H) || !defined(_POSIX_BARRIERS) || \
  defined(__APPLE__)

/* Skip the test if no <stdatomic.h> or pthread_barrier_t or on macOS
 * which defines _POSIX_BARRIERS but doesn't actually have them.
 */

int
main (void)
{
  fprintf (stderr,
           "SKIP: no <stdatomic.h> or pthread_barrier_t on this platform\n");
  exit (77);
}

#else

#include <stdatomic.h>
#include <errno.h>

#undef NDEBUG /* Keep test strong even for nbdkit built without assertions */
#include <assert.h>

#include "once.h"

#define NR_THREADS 8

static volatile _Atomic unsigned count1 = 0, count2 = 0,
  count3 = 0, count4 = 0;
static pthread_barrier_t barrier;

static void * __attribute__((noreturn))
start_thread (void *idxp)
{
  //int idx = * (int*) idxp;

  pthread_barrier_wait (&barrier);

  for (;;) {
    ONCE (count1++);
    ONCE (count2++);
    ONCE (count3++);
    ONCE (count4++);
  }
}

int
main (void)
{
  int i, err;
  pthread_t th[NR_THREADS];
  int idx[NR_THREADS];

  err = pthread_barrier_init (&barrier, NULL, NR_THREADS);
  if (err != 0) {
    errno = err;
    perror ("pthread_barrier_init");
    exit (EXIT_FAILURE);
  }

  for (i = 0; i < NR_THREADS; ++i) {
    idx[i] = i;
    err = pthread_create (&th[i], NULL, start_thread, &idx[i]);
    if (err != 0) {
      errno = err;
      perror ("pthread_create");
      exit (EXIT_FAILURE);
    }
  }

  do {
    sleep (1);
  } while (count1 + count2 + count3 + count4 < 4);

  for (i = 0; i < NR_THREADS; ++i) {
    pthread_cancel (th[i]);
  }

  pthread_barrier_destroy (&barrier);

  if (count1 != 1 || count2 != 1 || count3 != 1 || count4 != 1) {
    fprintf (stderr, "FAIL: counts incremented to %u %u %u %u "
             "(expected 1 1 1 1)\n", count1, count2, count3, count4);
    exit (EXIT_FAILURE);
  }

  exit (EXIT_SUCCESS);
}

#endif
