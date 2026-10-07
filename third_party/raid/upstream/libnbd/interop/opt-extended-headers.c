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

/* Demonstrate low-level use of nbd_opt_extended_headers(). */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/stat.h>

#include <libnbd.h>

#define check(got, exp) do_check (#got, got, exp)

static void
do_check (const char *act, int64_t got, int64_t exp)
{
  fprintf (stderr, "trying %s\n", act);
  if (got == -1)
    fprintf (stderr, "%s\n", nbd_get_error ());
  else
    fprintf (stderr, "succeeded, result %" PRId64 "\n", got);
  if (got != exp) {
    fprintf (stderr, "got %" PRId64 ", but expected %" PRId64 "\n", got, exp);
    exit (EXIT_FAILURE);
  }
}

static int
cb (void *data, const char *metacontext, uint64_t offset,
    nbd_extent *entries, size_t nr_entries, int *error)
{
  /* If we got here, extents worked, implying at least structured replies */
  bool *seen = data;

  *seen = true;
  return 0;
}

struct nbd_handle *
prep (bool sr, bool eh, char **cmd)
{
  struct nbd_handle *nbd;

  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Connect to the server in opt mode, disable client-side failsafes so
   * that we are testing server response even when client breaks protocol.
   */
  check (nbd_set_opt_mode (nbd, true), 0);
  check (nbd_set_strict_mode (nbd, 0), 0);
  check (nbd_add_meta_context (nbd, LIBNBD_CONTEXT_BASE_ALLOCATION), 0);
  check (nbd_set_request_structured_replies (nbd, sr), 0);
  check (nbd_set_request_extended_headers (nbd, eh), 0);
  check (nbd_connect_systemd_socket_activation (nbd, cmd), 0);

  return nbd;
}

void
cleanup (struct nbd_handle *nbd, bool extents_exp)
{
  bool extents = false;

  check (nbd_opt_go (nbd), 0);
  check (nbd_can_meta_context (nbd, LIBNBD_CONTEXT_BASE_ALLOCATION),
         extents_exp);
  check (nbd_block_status_64 (nbd, 512, 0,
                              (nbd_extent64_callback) { .callback = cb,
                                                        .user_data = &extents },
                              0), extents_exp ? 0 : -1);
  check (extents, extents_exp);
  nbd_close (nbd);
}

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  int64_t bytes_sent;

  if (argc < 2) {
    fprintf (stderr, "%s qemu-nbd [args ...]\n", argv[0]);
    exit (EXIT_FAILURE);
  }

  /* Default setup tries eh first, and skips sr request when eh works... */
  nbd = prep (true, true, &argv[1]);
  bytes_sent = nbd_stats_bytes_sent (nbd);
  check (nbd_get_extended_headers_negotiated (nbd), true);
  check (nbd_get_structured_replies_negotiated (nbd), true);
  /* Duplicate eh request is no-op as redundant, but does not change state */
  check (nbd_opt_extended_headers (nbd), false);
  /* Trying sr after eh is no-op as redundant, but does not change state */
  check (nbd_opt_structured_reply (nbd), false);
  check (nbd_get_extended_headers_negotiated (nbd), true);
  check (nbd_get_structured_replies_negotiated (nbd), true);
  cleanup (nbd, true);

  /* ...which should result in the same amount of initial negotiation
   * traffic as explicitly requesting just structured replies, albeit
   * with different results on what got negotiated.
   */
  nbd = prep (true, false, &argv[1]);
  check (nbd_stats_bytes_sent (nbd), bytes_sent);
  check (nbd_get_extended_headers_negotiated (nbd), false);
  check (nbd_get_structured_replies_negotiated (nbd), true);
  cleanup (nbd, true);

  /* request_eh is ignored if request_sr is false. */
  nbd = prep (false, true, &argv[1]);
  check (nbd_get_extended_headers_negotiated (nbd), false);
  check (nbd_get_structured_replies_negotiated (nbd), false);
  cleanup (nbd, false);

  /* Swap order, requesting structured replies before extended headers */
  nbd = prep (false, false, &argv[1]);
  check (nbd_get_extended_headers_negotiated (nbd), false);
  check (nbd_get_structured_replies_negotiated (nbd), false);
  check (nbd_opt_structured_reply (nbd), true);
  check (nbd_get_extended_headers_negotiated (nbd), false);
  check (nbd_get_structured_replies_negotiated (nbd), true);
  check (nbd_opt_extended_headers (nbd), true);
  check (nbd_get_extended_headers_negotiated (nbd), true);
  check (nbd_get_structured_replies_negotiated (nbd), true);
  cleanup (nbd, true);

  exit (EXIT_SUCCESS);
}
