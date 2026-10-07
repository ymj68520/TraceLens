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

/* Test connecting to a TCP port. */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <netinet/tcp.h>

#include <libnbd.h>

#include "pick-a-port.h"

#define PIDFILE "connect-tcp.pid"

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  int port = pick_a_port ();
  char port_str[16];
  pid_t pid;
  size_t i;
  char *actual_uri, *expected_uri;
  int r;

  unlink (PIDFILE);

  snprintf (port_str, sizeof port_str, "%d", port);

  pid = fork ();
  if (pid == -1) {
    perror ("fork");
    exit (EXIT_FAILURE);
  }
  if (pid == 0) {
    execlp (NBDKIT,
            "nbdkit", "-f", "-p", port_str, "-P", PIDFILE,
            "--exit-with-parent", "null", NULL);
    perror ("nbdkit");
    _exit (EXIT_FAILURE);
  }

  /* Wait for nbdkit to start listening. */
  for (i = 0; i < 60; ++i) {
    if (access (PIDFILE, F_OK) == 0)
      break;
    sleep (1);
  }
  unlink (PIDFILE);

  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Setting keepalive won't do anything for this short connection.
   * However it should be possible to set these parameters even on
   * non-Linux.
   */
  r = nbd_get_keepalive (nbd);
  if (r != 0) {
    fprintf (stderr, "expected nbd_get_keepalive == 0, but got %d\n", r);
    exit (EXIT_FAILURE);
  }
  nbd_set_keepalive (nbd, 1); /* in the current impl this cannot fail */
  r = nbd_get_keepalive (nbd);
  if (r != 1) {
    fprintf (stderr, "expected nbd_get_keepalive == 1, but got %d\n", r);
    exit (EXIT_FAILURE);
  }
#ifdef TCP_KEEPCNT
  nbd_set_tcp_option (nbd, TCP_KEEPCNT, 10);
#endif
#ifdef TCP_KEEPIDLE
  nbd_set_tcp_option (nbd, TCP_KEEPIDLE, 60);
#endif
#ifdef TCP_KEEPINTVL
  nbd_set_tcp_option (nbd, TCP_KEEPINTVL, 10);
#endif

  if (nbd_connect_tcp (nbd, "localhost", port_str) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* See if keepalive was established, but don't fail if it was not. */
  r = nbd_get_keepalive (nbd);
  printf ("nbd_get_keepalive after connection returned %d\n", r);
  fflush (stdout);

  if (nbd_supports_uri (nbd) == 1) {
    /* libnbd should be able to construct a URI for this connection. */
    if (asprintf (&expected_uri, "nbd://localhost:%s/", port_str) == -1) {
      perror ("asprintf");
      exit (EXIT_FAILURE);
    }
    actual_uri = nbd_get_uri (nbd);
    if (actual_uri == NULL) {
      fprintf (stderr, "%s\n", nbd_get_error ());
      exit (EXIT_FAILURE);
    }
    if (strcmp (actual_uri, expected_uri) != 0) {
      fprintf (stderr, "%s: actual URI %s != expected URI %s\n",
               argv[0], actual_uri, expected_uri);
      exit (EXIT_FAILURE);
    }
    free (actual_uri);
    free (expected_uri);
  }

  if (nbd_shutdown (nbd, 0) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  nbd_close (nbd);
  exit (EXIT_SUCCESS);
}
