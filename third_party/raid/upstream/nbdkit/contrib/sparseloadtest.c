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

/* Load nbdkit-memory-plugin + allocator=sparse
 *
 * This is better than fio for this plugin since it exercises
 * allocation and deallocation of pages and locking.
 *
 * To test a mainly read workload (90% reads, 10% writes, 10% trims):
 * ./contrib/sparseloadtest 4 90
 *
 * To test a write-heavy workload (20% reads, 40% writes, 40% trims):
 * ./contrib/sparseloadtest 4 20
 *
 * nbdkit is run from the current $PATH environment variable, so to
 * run the locally built nbdkit you should do:
 *
 * PATH=.:$PATH ./contrib/sparseloadtest [...]
 */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <signal.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <pthread.h>

#include <libnbd.h>

#include "random.h"

#define SPARSE_PAGE 32768       /* See common/allocators/sparse.c */
#define L2_SIZE     4096
#define DISK_SIZE   (4*L2_SIZE*SPARSE_PAGE)
#define MAX_THREADS 16
#define DURATION    60          /* seconds */
#define MAX_IN_FLIGHT 64
#define MAX_REQUEST (128*1024)  /* Should be larger than SPARSE_PAGE. */

static pid_t pid;
static char sockfile[] = "/tmp/sockXXXXXX";
static char pidfile[] = "/tmp/pidXXXXXX";
static unsigned nr_threads;
static double pc_read;          /* % read operations. */

struct stats {
  size_t ops;
  size_t bytes;
};

struct thread_data {
  pthread_t thread;
  int status;                   /* returned status from the thread */
  struct nbd_handle *nbd;       /* per-thread handle */
  struct stats read_stats, write_stats, trim_stats;
  struct random_state state;
};
static struct thread_data thread[MAX_THREADS];

static time_t start_t;

struct command_data {
  struct stats *stats;
  size_t count;
};

/* We don't care about the data that is read, so this is just a sink
 * buffer shared across all threads.
 */
static char sink[MAX_REQUEST];

static char wrbuf[MAX_REQUEST];

static void start_nbdkit (void);
static void create_random_name (char *template);
static void cleanup (void);
static void *start_thread (void *);

int
main (int argc, char *argv[])
{
  unsigned i;
  int err;
  struct stats read_total = { 0 };
  struct stats write_total = { 0 };
  struct stats trim_total = { 0 };

  if (argc != 3) {
    fprintf (stderr, "%s nr_threads percent_reads\n", argv[0]);
    exit (EXIT_FAILURE);
  }
  if (sscanf (argv[1], "%u", &nr_threads) != 1 ||
      nr_threads == 0 || nr_threads > MAX_THREADS ||
      sscanf (argv[2], "%lg", &pc_read) != 1 ||
      pc_read <= 0 || pc_read > 100) {
    fprintf (stderr, "%s: incorrect parameters, read the source!\n", argv[0]);
    exit (EXIT_FAILURE);
  }

  start_nbdkit ();
  atexit (cleanup);

  /* Connect to nbdkit. */
  for (i = 0; i < nr_threads; ++i) {
    struct nbd_handle *nbd = nbd_create ();
    if (nbd == NULL) {
    got_nbd_error:
      fprintf (stderr, "%s: thread %u: %s\n", argv[0], i, nbd_get_error ());
      exit (EXIT_FAILURE);
    }
    if (nbd_connect_unix (nbd, sockfile) == -1)
      goto got_nbd_error;
    thread[i].nbd = nbd;
  }

  time (&start_t);

  /* Start threads. */
  for (i = 0; i < nr_threads; ++i) {
    xsrandom (i+1, &thread[i].state);

    if (i == 0) {
      size_t j;
      for (j = 0; j < sizeof wrbuf; ++j)
        wrbuf[j] = xrandom (&thread[i].state);
    }

    err = pthread_create (&thread[i].thread, NULL, start_thread, &thread[i]);
    if (err != 0) {
      errno = err;
      perror ("pthread_create");
      exit (EXIT_FAILURE);
    }
  }

  /* Wait for the threads to exit. */
  for (i = 0; i < nr_threads; ++i) {
    err = pthread_join (thread[i].thread, NULL);
    if (err != 0) {
      errno = err;
      perror ("pthread_join");
      exit (EXIT_FAILURE);
    }
    if (thread[i].status != 0) {
      fprintf (stderr, "%s: thread %u failed, see earlier errors\n",
               argv[0], i);
      exit (EXIT_FAILURE);
    }

    read_total.ops += thread[i].read_stats.ops;
    read_total.bytes += thread[i].read_stats.bytes;
    write_total.ops += thread[i].write_stats.ops;
    write_total.bytes += thread[i].write_stats.bytes;
    trim_total.ops += thread[i].trim_stats.ops;
    trim_total.bytes += thread[i].trim_stats.bytes;

    /* Drain the command queue just to avoid errors.  These requests
     * don't count in the final totals.
     */
    while (nbd_aio_in_flight (thread[i].nbd) > 0) {
      if (nbd_poll (thread[i].nbd, -1) == -1) {
        fprintf (stderr, "%s\n", nbd_get_error ());
        exit (EXIT_FAILURE);
      }
    }

    nbd_close (thread[i].nbd);
  }

  /* Print the throughput. */
  printf ("READ: %.1f ops/s %.1f bytes/s\n",
          (double) read_total.ops / DURATION,
          (double) read_total.bytes / DURATION);
  printf ("WRITE: %.1f ops/s %.1f bytes/s\n",
          (double) write_total.ops / DURATION,
          (double) write_total.bytes / DURATION);
  printf ("TRIM: %.1f ops/s %.1f bytes/s\n",
          (double) trim_total.ops / DURATION,
          (double) trim_total.bytes / DURATION);
  printf ("TOTAL: %.1f ops/s %.1f bytes/s\n",
          (double) (read_total.ops + write_total.ops + trim_total.ops)
          / DURATION,
          (double) (read_total.bytes + write_total.bytes + trim_total.bytes)
          / DURATION);
  printf ("--\n");
  printf ("%%read operations requested: %.1f%%, achieved: %.1f%%\n",
          pc_read,
          100.0 * read_total.ops /
          (read_total.ops + write_total.ops + trim_total.ops));
  printf ("%%write operations requested: %.1f%%, achieved: %.1f%%\n",
          (100 - pc_read) / 2,
          100.0 * write_total.ops /
          (read_total.ops + write_total.ops + trim_total.ops));
  printf ("%%trim operations requested: %.1f%%, achieved: %.1f%%\n",
          (100 - pc_read) / 2,
          100.0 * trim_total.ops /
          (read_total.ops + write_total.ops + trim_total.ops));

  exit (EXIT_SUCCESS);
}

static void
cleanup (void)
{
  if (pid > 0) {
    kill (pid, SIGTERM);
    unlink (sockfile);
    pid = 0;
  }
}

/* Start nbdkit.
 *
 * We cannot use systemd socket activation because we want to use
 * multi-conn.
 */
static void
start_nbdkit (void)
{
  char size[64];
  int i;

  snprintf (size, sizeof size, "%d", DISK_SIZE);

  create_random_name (sockfile);
  create_random_name (pidfile);

  /* Start nbdkit. */
  pid = fork ();
  if (pid == -1) {
    perror ("fork");
    exit (EXIT_FAILURE);
  }
  if (pid == 0) {               /* Child - nbdkit */
    execlp ("nbdkit",
            "nbdkit", "--exit-with-parent", "-f",
            "-U", sockfile, "-P", pidfile,
            "memory", size, "allocator=sparse",
            NULL);
    perror ("execlp");
    _exit (EXIT_FAILURE);
  }

  /* Wait for the pidfile to appear, indicating that nbdkit is ready. */
  for (i = 0; i < 60; ++i) {
    if (access (pidfile, F_OK) == 0)
      break;
    sleep (1);
  }
  if (i == 60) {
    fprintf (stderr, "nbdkit did not start up, look for errors above\n");
    exit (EXIT_FAILURE);
  }

  unlink (pidfile);
}

/* This is racy but it doesn't matter for a test. */
static void
create_random_name (char *template)
{
  int fd;

  fd = mkstemp (template);
  if (fd == -1) {
    perror (template);
    exit (EXIT_FAILURE);
  }
  close (fd);
  unlink (template);
}

static int
cb (void *user_data, int *error)
{
  struct command_data *data = user_data;

  if (*error != 0) {
    fprintf (stderr, "unexpected error in completion callback\n");
    exit (EXIT_FAILURE);
  }

  data->stats->ops++;
  data->stats->bytes += data->count;

  free (data);

  return 1;                     /* retire the command */
}

static void *
start_thread (void *thread_data_vp)
{
  struct thread_data *thread_data = thread_data_vp;
  struct nbd_handle *nbd = thread_data->nbd;
  time_t end_t;
  size_t total_ops;
  double pc_read_actual;
  uint64_t offset;
  size_t count;
  struct command_data *data;
  int64_t r;

  while (time (&end_t), end_t - start_t < DURATION) {
    /* Run the poll loop if there are too many requests in flight. */
    while (nbd_aio_in_flight (nbd) >= MAX_IN_FLIGHT) {
      if (nbd_poll (nbd, -1) == -1) {
        fprintf (stderr, "%s\n", nbd_get_error ());
        exit (EXIT_FAILURE);
      }
    }

    /* Aim to send about pc_read% read operations, and an equal random
     * distribution of writes and trims.
     */
    total_ops =
      thread_data->read_stats.ops + thread_data->write_stats.ops +
      thread_data->trim_stats.ops;
    if (total_ops == 0)
      pc_read_actual = 100;
    else
      pc_read_actual = 100 * (thread_data->read_stats.ops / (double) total_ops);

    offset = xrandom (&thread_data->state) & (DISK_SIZE - MAX_REQUEST);
    count = xrandom (&thread_data->state) & (MAX_REQUEST - 1);
    if (count == 0) count = 1;

    data = malloc (sizeof *data); /* freed in callback */
    data->count = count;

    if (pc_read_actual < pc_read) { /* read op */
      data->stats = &thread_data->read_stats;
      r = nbd_aio_pread (nbd, sink, count, offset,
                         (nbd_completion_callback) {
                           .callback = cb,
                           .user_data = data,
                         }, 0);
    }
    else {
      if (xrandom (&thread_data->state) & 1) { /* write op */
        data->stats = &thread_data->write_stats;
        r = nbd_aio_pwrite (nbd, wrbuf, count, offset,
                            (nbd_completion_callback) {
                              .callback = cb,
                              .user_data = data,
                            }, 0);
      }
      else {                    /* trim op */
        data->stats = &thread_data->trim_stats;
        r = nbd_aio_trim (nbd, count, offset,
                          (nbd_completion_callback) {
                            .callback = cb,
                            .user_data = data,
                          }, 0);
      }
    }
    if (r == -1) {
      fprintf (stderr, "%s\n", nbd_get_error ());
      exit (EXIT_FAILURE);
    }
  }

  return NULL;
}
