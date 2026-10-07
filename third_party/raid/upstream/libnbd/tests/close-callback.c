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

/* Check that nbd_close callbacks work. */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <assert.h>

#include <libnbd.h>

static int
set_to_1 (void *vp)
{
  int *i = vp;

  printf ("set_to_1: %d -> 1\n", *i);
  fflush (stdout);
  *i = 1;
  return 0;
}

static int
set_to_2 (void *vp)
{
  int *i = vp;

  printf ("set_to_2: %d -> 2\n", *i);
  fflush (stdout);
  *i = 2;
  return 0;
}

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd1, *nbd2;
  int a = 0, b = 0;
  void *data;

  nbd1 = nbd_create ();
  if (nbd1 == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  nbd2 = nbd_create ();
  if (nbd2 == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Add some close callbacks to both handles. */
  nbd_add_close_callback (nbd1,
                          (nbd_close_callback){ .callback = set_to_1,
                                                .user_data = &a });
  nbd_add_close_callback (nbd1,
                          (nbd_close_callback){ .callback = set_to_2,
                                                .user_data = &b });
  nbd_add_close_callback (nbd2,
                          (nbd_close_callback){ .callback = set_to_2,
                                                .user_data = &a });

  /* This tests that the callback is freed only once.  It relies on
   * the C library detecting double frees.
   */
  data = malloc (64);
  assert (data);
  nbd_add_close_callback (nbd1,
                          (nbd_close_callback){ .user_data = data,
                                                .free = free });

  /* Initial state. */
  assert (a == 0);
  assert (b == 0);

  /* Close the first handle. */
  nbd_close (nbd1);
  assert (a == 1);
  assert (b == 2);

  /* Close the second handle. */
  nbd_close (nbd2);
  assert (a == 2);
  assert (b == 2);

  exit (EXIT_SUCCESS);
}
