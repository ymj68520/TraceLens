/* The example benchmarks multiple parallel connections to an NBD
 * server.  You can use it to time how long it takes to connect under
 * various circumstances (eg. TLS vs no TLS, old vs newstyle).  It
 * only does the NBD handshake and then immediately disconnects.
 *
 * Typical usage:
 *   ./examples/connect-benchmark nbd://localhost 16 1000
 * where the parameters are:
 *   URI of the server
 *   number of threads
 *   total number of connections to make (across all threads)
 *
 * Or:
 *   nbdkit null --run './examples/connect-benchmark "$uri" 16 1000'
 *
 * Use 'hyperfine' to time multiple runs.
 */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <errno.h>

#ifdef HAVE_STDATOMIC_H
#include <stdatomic.h>
#else
/* Rely on ints being atomic enough on the platform. */
#define _Atomic /**/
#endif

#include <pthread.h>

#include <libnbd.h>

static const char *uri;
static unsigned nr_threads, nr_connections;
static _Atomic unsigned count = 0;

static void *start_thread (void *arg);

int
main (int argc, char *argv[])
{
  pthread_t *threads;
  unsigned i;
  int err;

  if (argc != 4) {
    fprintf (stderr, "%s URI threads connections\n", argv[0]);
    exit (EXIT_FAILURE);
  }
  uri = argv[1];
  if (sscanf (argv[2], "%u", &nr_threads) != 1 ||
      sscanf (argv[3], "%u", &nr_connections) != 1) {
    fprintf (stderr, "%s: cannot read number of threads or connections\n",
             argv[0]);
    exit (EXIT_FAILURE);
  }

  threads = calloc (nr_threads, sizeof threads[0]);
  if (threads == NULL) {
    perror ("calloc");
    exit (EXIT_FAILURE);
  }

  /* Start the worker threads, one per connection. */
  for (i = 0; i < nr_threads; ++i) {
    err = pthread_create (&threads[i], NULL, start_thread, NULL);
    if (err != 0) {
      errno = err;
      perror ("pthread_create");
      exit (EXIT_FAILURE);
    }
  }

  /* Wait for the threads to exit. */
  for (i = 0; i < nr_threads; ++i) {
    err = pthread_join (threads[i], NULL);
    if (err != 0) {
      errno = err;
      perror ("pthread_join");
      exit (EXIT_FAILURE);
    }
  }

  exit (EXIT_SUCCESS);
}

static void *
start_thread (void *arg)
{
  struct nbd_handle *nbd;
  unsigned i;

  for (;;) {
    i = count++;
    if (i >= nr_connections) break;

    nbd = nbd_create ();
    if (nbd == NULL) {
      fprintf (stderr, "%s\n", nbd_get_error ());
      exit (EXIT_FAILURE);
    }

    if (nbd_connect_uri (nbd, uri) == -1) {
      fprintf (stderr, "%s\n", nbd_get_error ());
      exit (EXIT_FAILURE);
    }

    nbd_close (nbd);
  }

  pthread_exit (NULL);
}
