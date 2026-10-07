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

/* Test shutdown in relation to opt mode.
 */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <signal.h>

#include <libnbd.h>

static const char *progname;

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  const char *cmd_old[] = { NBDKIT, "--oldstyle", "-s", "--exit-with-parent",
                            "memory", "size=2m", NULL };
  const char *cmd_new[] = { NBDKIT, "-s", "--exit-with-parent",
                            "memory", "size=2m", NULL };

  progname = argv[0];

  /* Part 1: Request opt mode. With oldstyle, it is not possible. */
  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_set_opt_mode (nbd, true) == -1) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_connect_command (nbd, (char **)cmd_old) == -1) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_aio_is_ready (nbd) != 1) {
    fprintf (stderr, "%s: unexpected state\n", progname);
    exit (EXIT_FAILURE);
  }

  /* opt_abort fails, because we aren't in option negotiation. */
  if (nbd_opt_abort (nbd) != -1) {
    fprintf (stderr, "%s: unexpected success of nbd_opt_abort\n", progname);
    exit (EXIT_FAILURE);
  }
  if (nbd_get_errno () != EINVAL) {
    fprintf (stderr, "%s: test failed: unexpected errno: %s\n",
             progname, strerror (nbd_get_errno ()));
    exit (EXIT_FAILURE);
  }
  /* Shutdown will succeed, since opt mode was not possible. */
  if (nbd_shutdown (nbd, 0) == -1) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  nbd_close (nbd);

  /* Part 2: Request opt mode. With newstyle, it succeeds. */
  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_set_opt_mode (nbd, true) == -1) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_connect_command (nbd, (char **)cmd_new) == -1) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_aio_is_negotiating (nbd) != 1) {
    fprintf (stderr, "%s: unexpected state\n", progname);
    exit (EXIT_FAILURE);
  }

  /* Disconnect fails, because we are in wrong mode.  */
  if (nbd_aio_disconnect (nbd, 0) != -1) {
    fprintf (stderr,
             "%s: test failed: nbd_aio_disconnect unexpectedly worked\n",
             progname);
    exit (EXIT_FAILURE);
  }
  if (nbd_get_errno () != EINVAL) {
    fprintf (stderr, "%s: test failed: unexpected errno: %s\n",
             progname, strerror (nbd_get_errno ()));
    exit (EXIT_FAILURE);
  }
  /* But we can manually call nbd_opt_abort, which closes gracefully. */
  if (nbd_opt_abort (nbd) == -1) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_aio_is_closed (nbd) != 1) {
    fprintf (stderr, "%s: unexpected state\n", progname);
    exit (EXIT_FAILURE);
  }
  nbd_close (nbd);

  /* Part 3: Shutdown works by default, regardless of opt mode */
  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_set_opt_mode (nbd, true) == -1) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_connect_command (nbd, (char **)cmd_new) == -1) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_aio_is_negotiating (nbd) != 1) {
    fprintf (stderr, "%s: unexpected state\n", progname);
    exit (EXIT_FAILURE);
  }

  /* Shutdown succeeds; it does more than just aio_disconnect. */
  if (nbd_shutdown (nbd, 0) == -1) {
    fprintf (stderr, "%s: %s\n", progname, nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  nbd_close (nbd);

  exit (EXIT_SUCCESS);
}
