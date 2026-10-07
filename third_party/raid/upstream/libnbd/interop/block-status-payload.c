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

/* Test interaction with qemu using block status payload filtering. */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <assert.h>
#include <stdbool.h>
#include <errno.h>

#include <libnbd.h>

#include "array-size.h"

static const char *contexts[] = {
  "base:allocation",
  "qemu:allocation-depth",
  "qemu:dirty-bitmap:bitmap0",
  "qemu:dirty-bitmap:bitmap1",
};

static int
cb (void *opaque, const char *metacontext, uint64_t offset,
    nbd_extent *entries, size_t len, int *error)
{
  /* Adjust seen according to which context was visited */
  unsigned int *seen = opaque;
  size_t i;

  for (i = 0; i < ARRAY_SIZE (contexts); i++)
    if (strcmp (contexts[i], metacontext) == 0)
      break;
  *seen |= 1 << i;
  return 0;
}

static char **
list (unsigned int use)
{
  static const char *array[ARRAY_SIZE (contexts) + 1];
  size_t i, j;

  assert (use < 1 << ARRAY_SIZE (contexts));
  for (i = j = 0; i < ARRAY_SIZE (contexts); i++)
    if (use & (1 << i))
      array[j++] = contexts[i];
  array[j] = NULL;
  return (char **) array;
}

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  int64_t exportsize;
  uint64_t bytes_sent;
  unsigned int seen;
  size_t i;
  int r;

  if (argc < 2) {
    fprintf (stderr, "%s qemu-nbd [args ...]\n", argv[0]);
    exit (EXIT_FAILURE);
  }

  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  assert (ARRAY_SIZE (contexts) == 4);
  for (i = 0; i < ARRAY_SIZE (contexts); i++) {
    if (nbd_add_meta_context (nbd, contexts[i]) == -1) {
      fprintf (stderr, "%s\n", nbd_get_error ());
      exit (EXIT_FAILURE);
    }
  }

  if (nbd_connect_systemd_socket_activation (nbd, &argv[1]) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  r = nbd_can_block_status_payload (nbd);
  if (r == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (r != 1) {
    fprintf (stderr, "expecting block status payload support from qemu\n");
    exit (EXIT_FAILURE);
  }

  exportsize = nbd_get_size (nbd);
  if (exportsize == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* An unfiltered call should see all four contexts */
  seen = 0;
  if (nbd_block_status_64 (nbd, exportsize, 0,
                           (nbd_extent64_callback) { .callback = cb,
                                                     .user_data = &seen },
                           0) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  assert (seen == 0xf);

  /* Filtering with all contexts listed, same effect as unfilitered call */
  seen = 0;
  if (nbd_block_status_filter (nbd, exportsize, 0, list (0xf),
                               (nbd_extent64_callback) { .callback = cb,
                                                         .user_data = &seen },
                               0) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  assert (seen == 0xf);

  /* Filtering with just two out of four contexts; test optional flag */
  seen = 0;
  if (nbd_block_status_filter (nbd, exportsize, 0, list (0x5),
                               (nbd_extent64_callback) { .callback = cb,
                                                         .user_data = &seen },
                               LIBNBD_CMD_FLAG_PAYLOAD_LEN) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  assert (seen == 0x5);

  /* Filtering with one context, near end of file (to make sure the
   * payload length isn't confused with the effect length)
   */
  seen = 0;
  if (nbd_block_status_filter (nbd, 1, exportsize - 1, list (0x2),
                               (nbd_extent64_callback) { .callback = cb,
                                                         .user_data = &seen },
                               0) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  assert (seen == 0x2);

  /* Filtering with no contexts - pointless, so qemu rejects it */
  bytes_sent = nbd_stats_bytes_sent (nbd);
  seen = 0;
  if (nbd_block_status_filter (nbd, exportsize, 0, list (0x0),
                               (nbd_extent64_callback) { .callback = cb,
                                                         .user_data = &seen },
                               0) != -1) {
    fprintf (stderr, "expecting block status failure\n");
    exit (EXIT_FAILURE);
  }
  assert (seen == 0x0);
  if (nbd_get_errno () != EINVAL) {
    fprintf (stderr, "expecting EINVAL after block status failure\n");
    exit (EXIT_FAILURE);
  }
  if (nbd_stats_bytes_sent (nbd) <= bytes_sent) {
    fprintf (stderr, "expecting server-side rejection of bad request\n");
    exit (EXIT_FAILURE);
  }

  /* Giving unknown string triggers EINVAL from libnbd */
  bytes_sent = nbd_stats_bytes_sent (nbd);
  seen = 0;
  {
    const char *bogus[] = { "qemu:dirty-bitmap:bitmap2", NULL };
    if (nbd_block_status_filter (nbd, exportsize, 0, (char **) bogus,
                                 (nbd_extent64_callback) { .callback = cb,
                                                           .user_data = &seen },
                                 0) != -1) {
      fprintf (stderr, "expecting block status failure\n");
      exit (EXIT_FAILURE);
    }
  }
  if (nbd_get_errno () != EINVAL) {
    fprintf (stderr, "expecting EINVAL after block status failure\n");
    exit (EXIT_FAILURE);
  }
  assert (seen == 0x0);
  if (nbd_stats_bytes_sent (nbd) != bytes_sent) {
    fprintf (stderr, "expecting client-side rejection of bad request\n");
    exit (EXIT_FAILURE);
  }

  /* Giving same string twice triggers EINVAL from qemu */
  seen = 0;
  {
    const char *dupes[] = { "base:allocation", "base:allocation", NULL };
    if (nbd_block_status_filter (nbd, exportsize, 0, (char **) dupes,
                                 (nbd_extent64_callback) { .callback = cb,
                                                           .user_data = &seen },
                                 0) != -1) {
      fprintf (stderr, "expecting block status failure\n");
      exit (EXIT_FAILURE);
    }
  }
  if (nbd_get_errno () != EINVAL) {
    fprintf (stderr, "expecting EINVAL after block status failure\n");
    exit (EXIT_FAILURE);
  }
  assert (seen == 0x0);
  if (nbd_stats_bytes_sent (nbd) <= bytes_sent) {
    fprintf (stderr, "expecting server-side rejection of bad request\n");
    exit (EXIT_FAILURE);
  }

  /* Done */
  if (nbd_shutdown (nbd, 0) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  nbd_close (nbd);

  exit (EXIT_SUCCESS);
}
