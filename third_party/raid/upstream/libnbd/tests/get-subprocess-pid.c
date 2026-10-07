/* NBD client library in userspace
 * Copyright Red Hat
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

/* Check nbd_get_subprocess_pid looks sensible. */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <unistd.h>

#include <libnbd.h>

static char pidfile[] = "/tmp/libnbd-pid-XXXXXX";

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  int fd;
  int64_t pid;
  FILE *fp;
  char line[80];
  const char *cmd[] = { NBDKIT,
                        "-s", "--exit-with-parent",
                        "-P", pidfile,
                        "memory", "size=1m", NULL };

  if ((fd = mkstemp (pidfile)) == -1) {
    perror (pidfile);
    exit (EXIT_FAILURE);
  }
  close (fd);

  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s: %s\n", argv[0], nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  if (nbd_connect_command (nbd, (char **)cmd) == -1) {
    fprintf (stderr, "%s: %s\n", argv[0], nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  pid = nbd_get_subprocess_pid (nbd);
  if (pid == -1) {
    fprintf (stderr, "%s: %s\n", argv[0], nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  printf ("nbd_get_subprocess_pid returned %" PRIi64 "\n", pid);

  nbd_close (nbd);

  fp = fopen (pidfile, "r");
  if (fp == NULL) {
  pidfile_error:
    fprintf (stderr, "%s: nbdkit did not write a pidfile: %m\n", argv[0]);
    exit (EXIT_FAILURE);
  }
  if (fgets (line, sizeof line, fp) == NULL)
    goto pidfile_error;
  fclose (fp);
  unlink (pidfile);

  printf ("PID file written by nbdkit: %s", line);

  /* The two PIDs should match.  We could compare the two PIDs, but we
   * don't as this might not work on all platforms and this is
   * essentially a debugging API.
   */

  exit (EXIT_SUCCESS);
}
