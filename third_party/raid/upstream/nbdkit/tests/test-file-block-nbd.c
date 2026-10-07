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
#include <unistd.h>
#include <sys/types.h>

#include <libnbd.h>

#include "requires.h"

#define DISK_SIZE (100 * 1024 * 1024)

static char *loopdev;                   /* Name of the loop device. */
static void detach_loopdev (void);

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  int r;
  int fd;
  char cmd[64], buf[64];
  char disk[] = LARGE_TMPDIR "/diskXXXXXX"; /* Backing disk. */
  FILE *pp;
  size_t len;
  int64_t size;

  /* This test must be run as root (usually 'sudo make check-root'),
   * otherwise skip.
   */
  requires_root ();

  /* /dev/loop-control must be accessible. */
  r = access ("/dev/loop-control", W_OK);
  if (r != 0) {
    fprintf (stderr, "%s: /dev/loop-control is not writable.\n",
             argv[0]);
    exit (77);
  }

  /* losetup must be available. */
  requires ("losetup --version");

  /* Create the temporary backing disk. */
  fd = mkstemp (disk);
  if (fd == -1) {
    perror ("mkstemp");
    exit (EXIT_FAILURE);
  }
  if (ftruncate (fd, DISK_SIZE) == -1) {
    perror ("ftruncate");
    unlink (disk);
    exit (EXIT_FAILURE);
  }

  /* Create the loopback device. */
  snprintf (cmd, sizeof cmd, "losetup -f --show %s", disk);
  pp = popen (cmd, "r");
  if (pp == NULL) {
    perror ("popen: losetup");
    unlink (disk);
    exit (EXIT_FAILURE);
  }
  if (fgets (buf, sizeof buf, pp) == NULL) {
    fprintf (stderr, "%s: could not read loop device name from losetup\n",
             argv[0]);
    unlink (disk);
    exit (EXIT_FAILURE);
  }
  len = strlen (buf);
  if (len > 0 && buf[len-1] == '\n') {
    buf[len-1] = '\0';
    len--;
  }
  pclose (pp);

  /* We can delete the backing disk.  The loop device will hold it open. */
  unlink (disk);

  /* If we get to this point, set up an atexit handler to detach the
   * loop device.
   */
  loopdev = malloc (len+1);
  if (loopdev == NULL) {
    perror ("malloc");
    exit (EXIT_FAILURE);
  }
  strcpy (loopdev, buf);
  atexit (detach_loopdev);

  /* Create the nbd handle. */
  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Start nbdkit. */
  if (nbd_connect_command (nbd,
                           (char *[]) {
                             "nbdkit", "-s", "--exit-with-parent",
                             "file", loopdev,
                             NULL }) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Check the disk size matches the loop device size. */
  size = nbd_get_size (nbd);
  if (size == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (size != DISK_SIZE) {
    fprintf (stderr, "%s: incorrect export size, "
             "expected: %d actual: %" PRIi64 "\n",
             argv[0], DISK_SIZE, size);
    exit (EXIT_FAILURE);
  }

  /* Print (don't check) the block size preferences. */
  printf ("minimum = %" PRIu64 "\n",
          nbd_get_block_size (nbd, LIBNBD_SIZE_MINIMUM));
  printf ("preferred = %" PRIu64 "\n",
          nbd_get_block_size (nbd, LIBNBD_SIZE_PREFERRED));
  printf ("maximum = %" PRIu64 "\n",
          nbd_get_block_size (nbd, LIBNBD_SIZE_MAXIMUM));

  nbd_close (nbd);

  /* The atexit handler should detach the loop device and clean up
   * the backing disk.
   */
  exit (EXIT_SUCCESS);
}

/* atexit handler. */
static void
detach_loopdev (void)
{
  char cmd[64];

  if (loopdev == NULL)
    return;

  snprintf (cmd, sizeof cmd, "losetup -d %s", loopdev);
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-result"
  system (cmd);
#pragma GCC diagnostic pop
  free (loopdev);
  loopdev = NULL;
}
