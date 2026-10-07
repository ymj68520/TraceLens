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

/* Deliberately provoke some errors and check the error messages from
 * nbd_get_error etc look reasonable.
 */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>

#include <libnbd.h>

static char *progname;

static void
check (int experr, const char *prefix)
{
  const char *msg = nbd_get_error ();
  int errnum = nbd_get_errno ();

  fprintf (stderr, "error: \"%s\"\n", msg);
  fprintf (stderr, "errno: %d (%s)\n", errnum, strerror (errnum));
  if (strncmp (msg, prefix, strlen (prefix)) != 0) {
    fprintf (stderr, "%s: test failed: missing context prefix: %s\n",
             progname, msg);
    exit (EXIT_FAILURE);
  }
  if (errnum != experr) {
    fprintf (stderr, "%s: test failed: "
             "expected errno = %d (%s), but got %d\n",
             progname, experr, strerror (experr), errnum);
    exit (EXIT_FAILURE);
  }
}

struct progress {
  int id;
  bool call_freed;
  bool comp_freed;
};

static int
list_call (void *user_data, const char *name, const char *description)
{
  struct progress *p = user_data;

  fprintf (stderr, "%s: list callback should not be reached, iter %d\n",
           progname, p->id);
  exit (EXIT_FAILURE);
}

static void
list_free (void *user_data)
{
  struct progress *p = user_data;

  if (p->comp_freed) {
    fprintf (stderr, "%s: list free called too late, iter %d\n",
             progname, p->id);
    exit (EXIT_FAILURE);
  }
  p->call_freed = true;
}

static int
comp_call (void *user_data, int *error)
{
  struct progress *p = user_data;

  fprintf (stderr, "%s: list callback should not be reached, iter %d\n",
           progname, p->id);
  exit (EXIT_FAILURE);
}

static void
comp_free (void *user_data)
{
  struct progress *p = user_data;

  if (!p->call_freed) {
    fprintf (stderr, "%s: completion free called too early, iter %d\n",
             progname, p->id);
    exit (EXIT_FAILURE);
  }
  p->comp_freed = true;
}

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  const char *cmd[] = {
    NBDKIT, "-s", "-v", "--exit-with-parent", "memory", "1048576", NULL
  };
  struct progress p;
  nbd_list_callback list_cb = { .callback = list_call,
                                .user_data = &p,
                                .free = list_free };
  nbd_completion_callback comp_cb = { .callback = comp_call,
                                      .user_data = &p,
                                      .free = comp_free };

  progname = argv[0];

  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Too early to try nbd_aio_opt_*. */
  p = (struct progress) { .id = 0 };
  if (nbd_aio_opt_list (nbd, list_cb, comp_cb) != -1) {
    fprintf (stderr, "%s: test failed: "
             "nbd_aio_opt_list did not reject attempt in wrong state\n",
             argv[0]);
    exit (EXIT_FAILURE);
  }
  check (ENOTCONN, "nbd_aio_opt_list: ");
  if (!p.call_freed || !p.comp_freed) {
    fprintf (stderr, "%s: test failed: "
             "nbd_aio_opt_list did not call .free callbacks\n",
             argv[0]);
    exit (EXIT_FAILURE);
  }

  /* Connect to the server without requesting negotiation mode. */
  if (nbd_connect_command (nbd, (char **)cmd) == -1) {
    fprintf (stderr, "%s: %s\n", argv[0], nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Too late to try nbd_aio_opt_*. */
  p = (struct progress) { .id = 1 };
  if (nbd_aio_opt_list (nbd, list_cb, comp_cb) != -1) {
    fprintf (stderr, "%s: test failed: "
             "nbd_aio_opt_list did not reject attempt in wrong state\n",
             argv[0]);
    exit (EXIT_FAILURE);
  }
  check (EINVAL, "nbd_aio_opt_list: ");
  if (!p.call_freed || !p.comp_freed) {
    fprintf (stderr, "%s: test failed: "
             "nbd_aio_opt_list did not call .free callbacks\n",
             argv[0]);
    exit (EXIT_FAILURE);
  }

  nbd_close (nbd);
  exit (EXIT_SUCCESS);
}
