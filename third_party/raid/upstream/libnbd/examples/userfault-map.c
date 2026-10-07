/* This example shows how to memory map a drive using userfaultfd(2)
 * to map in pages which are read from the remote disk using libnbd.
 *
 * Because it is an example, we just compute a simple histogram over
 * the data to prove it works, but a real program could do something
 * else with the memory-mapped drive.  A real program also ought to
 * handle userfaultfd events in parallel, and use nbd_aio_* operations
 * to better utilise the NBD socket.
 *
 * It requires Linux >= 4.11.  On other platforms it will print an
 * error instead.
 *
 * To try out this example with nbdkit:
 *
 *   nbdkit -U - random 1M --run './userfault-map $uri'
 *
 * (set LIBNBD_DEBUG=1 for more detail)
 */

#include "config.h" /* For HAVE_* macros below */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <inttypes.h>
#include <string.h>
#include <unistd.h>

#ifdef HAVE_SYS_SYSCALL_H
#include <sys/syscall.h>
#endif

#if !defined(HAVE_SYS_SYSCALL_H) ||               \
    !defined(HAVE_LINUX_USERFAULTFD_H) ||         \
    !defined(__NR_userfaultfd)

int
main (int argc, char *argv[])
{
  fprintf (stderr, "%s: This program requires Linux >= 4.11\n", argv[0]);
  exit (EXIT_FAILURE);
}

#else

/* Here we can assume this is Linux so we don't need to use autoconf
 * portability macros.
 */

#include <fcntl.h>
#include <errno.h>
#include <assert.h>
#include <pthread.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <linux/userfaultfd.h>

#include <libnbd.h>

static struct nbd_handle *nbd;  /* libnbd handle. */
static int fd;                  /* Userfault file descriptor. */
static long page_size;          /* Machine page size. */
static int64_t size;            /* Size in bytes. */
static int64_t size_aligned;    /* Rounded up to next page size boundary. */
static void *memory;            /* Memory mapped drive. */

/* Background thread which handles userfaultfd events. */
static pthread_t thread;
static pthread_barrier_t barrier;
static void *handle_event (void *);

static void histogram (char *, size_t);

int
main (int argc, char *argv[])
{
  struct uffdio_api uffdio_api;
  struct uffdio_register uffdio_register;
  int err;

  if (argc != 2) {
    fprintf (stderr, "%s NBDURI\n", argv[0]);
    exit (EXIT_FAILURE);
  }

  /* Check we can use userfaultfd. */
  page_size = sysconf (_SC_PAGESIZE);
  if (page_size == -1) {
    perror ("sysconf");
    exit (EXIT_FAILURE);
  }
  assert (page_size > 0);

  fd = syscall (__NR_userfaultfd, O_CLOEXEC | O_NONBLOCK);
  if (fd == -1) {
    perror ("userfaultfd");
    exit (EXIT_FAILURE);
  }

  uffdio_api.api = UFFD_API;
  uffdio_api.features = 0;
  if (ioctl (fd, UFFDIO_API, &uffdio_api) == -1) {
    perror ("ioctl: UFFDIO_API");
    exit (EXIT_FAILURE);
  }

  if (uffdio_api.api != UFFD_API) {
    fprintf (stderr, "%s: unsupported userfaultfd API %lld != %lld\n",
             argv[0], uffdio_api.api, UFFD_API);
    exit (EXIT_FAILURE);
  }

  /* Create the libnbd handle. */
  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Connect to the server. */
  if (nbd_connect_uri (nbd, argv[1]) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  size = nbd_get_size (nbd);
  if (size == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  size_aligned = (size + page_size - 1) & -page_size;

  printf ("%s: connected to the NBD server\n", argv[0]);
  printf ("remote size (bytes):            %" PRIi64 "\n", size);
  printf ("allocation size (page aligned): %" PRIi64 "\n", size_aligned);
  fflush (stdout);

  /* mmap enough anonymous memory. */
  memory = mmap (NULL, size_aligned, PROT_READ, MAP_PRIVATE|MAP_ANONYMOUS,
                 -1, 0);
  if (memory == MAP_FAILED) {
    perror ("mmap");
    exit (EXIT_FAILURE);
  }

  /* Register the memory with userfaultfd. */
  uffdio_register.range.start = (unsigned long) memory;
  uffdio_register.range.len = size_aligned;
  uffdio_register.mode = UFFDIO_REGISTER_MODE_MISSING;
  if (ioctl (fd, UFFDIO_REGISTER, &uffdio_register) == -1) {
    perror ("ioctl: UFFDIO_REGISTER");
    exit (EXIT_FAILURE);
  }
#if 0
  if ((uffdio_register.ioctls & UFFD_API_RANGE_IOCTLS)
      != UFFD_API_RANGE_IOCTLS) {
    fprintf (stderr, "%s: unexpected userfaultfd ioctl range returned\n",
             argv[0]);
    exit (EXIT_FAILURE);
  }
#endif

  /* We need a background thread to handle userfaultfd events. */
  err = pthread_barrier_init (&barrier, NULL, 2);
  if (err != 0) {
    errno = err;
    perror ("pthread_barrier_init");
    exit (EXIT_FAILURE);
  }
  err = pthread_create (&thread, NULL, handle_event, NULL);
  if (err != 0) {
    errno = err;
    perror ("pthread_create");
    exit (EXIT_FAILURE);
  }

  /* Wait for the background thread to start. */
  pthread_barrier_wait (&barrier);
  pthread_barrier_destroy (&barrier);

  /* Prove you can pass the pointer to another function that works on
   * memory buffers.
   */
  printf ("Calculating byte histogram over drive ...\n");
  fflush (stdout);
  histogram (memory, size);

  /* Destroy the background thread. */
  printf ("Clean up and exit ...\n");
  fflush (stdout);
  pthread_cancel (thread);

  /* Close the libnbd handle. */
  nbd_close (nbd);

  exit (EXIT_SUCCESS);
}

static void *
handle_event (void *vp)
{
  char *buf;
  int oldstate;

  pthread_setcancelstate (PTHREAD_CANCEL_ENABLE, &oldstate);

  buf = malloc (page_size);
  if (buf == NULL) {
    perror ("malloc");
    exit (EXIT_FAILURE);
  }

  /* Ready to serve requests. */
  pthread_barrier_wait (&barrier);

  for (;;) {
    struct uffd_msg msg;
    struct pollfd pollfd[1];
    int r;
    uintptr_t addr;
    uint64_t offset;
    size_t len;
    struct uffdio_copy uffdio_copy;

    pollfd[0].fd = fd;
    pollfd[0].events = POLLIN;

    r = poll (pollfd, 1, -1);
    if (r == -1) {
      perror ("poll");
      exit (EXIT_FAILURE);
    }
    if (r == 0) continue;

    if ((pollfd[0].revents & POLLERR) != 0) {
      fprintf (stderr, "poll: unexpected POLLERR returned\n");
      exit (EXIT_FAILURE);
    }

    if ((pollfd[0].revents & POLLIN) != 0) {
      r = read (fd, &msg, sizeof msg);
      if (r == -1) {
        if (errno == EAGAIN || errno == EWOULDBLOCK)
          continue;
        perror ("read");
        exit (EXIT_FAILURE);
      }

      if (r != sizeof msg) {
        fprintf (stderr, "read: unexpected size of message\n");
        exit (EXIT_FAILURE);
      }

      if (msg.event & UFFD_EVENT_PAGEFAULT) {
        /* Finally, handle the page fault ... */
        addr = msg.arg.pagefault.address;

        /* Read the data from the remote server. */
        offset = addr - (uintptr_t) memory;
        len = page_size;
        if (offset + page_size > size) {
          len -= offset + page_size - size;
          memset (buf, 0, page_size);
        }
        if (nbd_pread (nbd, buf, len, offset, 0)
            == -1) {
          fprintf (stderr, "%s\n", nbd_get_error ());
          exit (EXIT_FAILURE);
        }

        /* Atomically write the result to the memory map.  We can't
         * use memcpy here as explained in AA's talk.
         */
        uffdio_copy.src = (uintptr_t)buf;
        uffdio_copy.dst = addr;
        uffdio_copy.len = page_size;
        uffdio_copy.mode = 0;
        if (ioctl (fd, UFFDIO_COPY, &uffdio_copy) == -1) {
          perror ("ioctl: UFFDIO_COPY");
          exit (EXIT_FAILURE);
        }
      }
    }
  }
}

static void
histogram (char *buf, size_t len)
{
  size_t i;
  int count[256] = { 0 };

  for (i = 0; i < len; ++i)
    count[(int)buf[i]]++;

  printf ("number of zero bytes found in input = %d / %zu\n",
          count[0], len);
}

#endif /* platform supports userfaultfd */
