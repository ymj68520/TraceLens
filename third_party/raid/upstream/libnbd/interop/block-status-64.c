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

/* Test 64-bit block status with qemu. */

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

static const char *bitmap;

struct data {
  bool req_one;    /* input: true if req_one was passed to request */
  int count;       /* input: count of expected remaining calls */
  bool seen_base;  /* output: true if base:allocation encountered */
  bool seen_dirty; /* output: true if qemu:dirty-bitmap encountered */
};

static int
cb32 (void *opaque, const char *metacontext, uint64_t offset,
      uint32_t *entries, size_t len, int *error)
{
  struct data *data = opaque;

  assert (offset == 0);
  assert (data->count-- > 0);

  if (strcmp (metacontext, LIBNBD_CONTEXT_BASE_ALLOCATION) == 0) {
    assert (!data->seen_base);
    data->seen_base = true;

    /* Data block offset 0 size 64k, remainder is hole */
    assert (len == 4);
    assert (entries[0] == 65536);
    assert (entries[1] == 0);
    /* libnbd had to truncate qemu's >4G answer */
    assert (entries[2] == 4227858432);
    assert (entries[3] == (LIBNBD_STATE_HOLE|LIBNBD_STATE_ZERO));
  }
  else if (strcmp (metacontext, bitmap) == 0) {
    assert (!data->seen_dirty);
    data->seen_dirty = true;

    /* Dirty block at offset 5G-64k, remainder is clean */
    /* libnbd had to truncate qemu's >4G answer */
    assert (len == 2);
    assert (entries[0] == 4227858432);
    assert (entries[1] == 0);
  }
  else {
    fprintf (stderr, "unexpected context %s\n", metacontext);
    exit (EXIT_FAILURE);
  }
  return 0;
}

static int
cb64 (void *opaque, const char *metacontext, uint64_t offset,
      nbd_extent *entries, size_t len, int *error)
{
  struct data *data = opaque;

  assert (offset == 0);
  assert (data->count-- > 0);

  if (strcmp (metacontext, LIBNBD_CONTEXT_BASE_ALLOCATION) == 0) {
    assert (!data->seen_base);
    data->seen_base = true;

    /* Data block offset 0 size 64k, remainder is hole */
    assert (len == 2);
    assert (entries[0].length == 65536);
    assert (entries[0].flags == 0);
    assert (entries[1].length == 5368643584ULL);
    assert (entries[1].flags == (LIBNBD_STATE_HOLE|LIBNBD_STATE_ZERO));
  }
  else if (strcmp (metacontext, bitmap) == 0) {
    assert (!data->seen_dirty);
    data->seen_dirty = true;

    /* Dirty block at offset 5G-64k, remainder is clean */
    assert (len == 2);
    assert (entries[0].length == 5368643584ULL);
    assert (entries[0].flags == 0);
    assert (entries[1].length == 65536);
    assert (entries[1].flags == 1);
  }
  else {
    fprintf (stderr, "unexpected context %s\n", metacontext);
    exit (EXIT_FAILURE);
  }
  return 0;
}

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  int64_t exportsize;
  struct data data;

  if (argc < 3) {
    fprintf (stderr, "%s bitmap qemu-nbd [args ...]\n", argv[0]);
    exit (EXIT_FAILURE);
  }
  bitmap = argv[1];

  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  nbd_add_meta_context (nbd, LIBNBD_CONTEXT_BASE_ALLOCATION);
  nbd_add_meta_context (nbd, bitmap);

  if (nbd_connect_systemd_socket_activation (nbd, &argv[2]) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  exportsize = nbd_get_size (nbd);
  if (exportsize == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  if (nbd_get_extended_headers_negotiated (nbd) != 1) {
    fprintf (stderr, "skipping: qemu-nbd lacks extended headers\n");
    nbd_close (nbd);
    exit (77);
  }

  /* Prove that we can round-trip a >4G block status request */
  data = (struct data) { .count = 2, };
  if (nbd_block_status_64 (nbd, exportsize, 0,
                           (nbd_extent64_callback) { .callback = cb64,
                             .user_data = &data },
                           0) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  assert (data.seen_base && data.seen_dirty);

  /* Check libnbd's handling of a >4G response through older interface  */
  data = (struct data) { .count = 2, };
  if (nbd_block_status (nbd, exportsize, 0,
                        (nbd_extent_callback) { .callback = cb32,
                          .user_data = &data },
                        0) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  assert (data.seen_base && data.seen_dirty);

  if (nbd_shutdown (nbd, 0) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  nbd_close (nbd);

  exit (EXIT_SUCCESS);
}
