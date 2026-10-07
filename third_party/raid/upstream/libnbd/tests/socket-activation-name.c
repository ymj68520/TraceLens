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

/* Test nbd_{set,get}_socket_activation_name API. */

#undef NDEBUG

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <assert.h>

#include <libnbd.h>

#include "requires.h"

#define DEBUG_FILE "socket-activation-name.out"
#define NAME "hellomagicname"

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  char *r;

  /* This requires nbdkit >= 1.48 (actually 1.47.5) which prints the
   * socket activation name in debugging output.
   */
  requires (NBDKIT " --version");
  requires ("minor=$( " NBDKIT " --dump-config |\n"
            "        grep ^version_minor | cut -d= -f2 )\n"
            "test $minor -ge 48");

  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Check firstly that it defaults to empty string. */
  r = nbd_get_socket_activation_name (nbd);
  assert (r != NULL);
  assert (strcmp (r, "") == 0);
  free (r);

  /* Check we can set it to something and read that back. */
  assert (nbd_set_socket_activation_name (nbd, NAME) == 0);
  r = nbd_get_socket_activation_name (nbd);
  assert (r != NULL);
  assert (strcmp (r, NAME) == 0);
  free (r);

  /* Run external nbdkit.  Capture the debug output of nbdkit, hence
   * the journey through the shell.
   */
  unlink (DEBUG_FILE);
  char *cmd[] = {
    "sh", "-c",
    "exec 2> " DEBUG_FILE "\n"
    "exec " NBDKIT " --exit-with-parent -v null 1024\n",
    NULL
  };

  /* Run external nbdkit. */
  if (nbd_connect_systemd_socket_activation (nbd, cmd) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  assert (nbd_get_size (nbd) == 1024);

  nbd_close (nbd);

  /* Check the name appears in the output. */
  assert (system ("grep 'debug.*" NAME "' " DEBUG_FILE) == 0);
  unlink (DEBUG_FILE);

  exit (EXIT_SUCCESS);
}
