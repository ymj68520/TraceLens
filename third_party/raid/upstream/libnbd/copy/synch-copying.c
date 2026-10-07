/* NBD client library in userspace.
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

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <assert.h>

#include <libnbd.h>

#include "minmax.h"
#include "nbdcopy.h"

/* Fill a range in dst with zeroes.  This is called from the copying
 * loop when we see a zero range in the source.  Depending on the
 * command line flags this could mean:
 *
 * --destination-is-zero:
 *                 do nothing
 *
 * --allocated:    write zeroes allocating space using an efficient
 *                 zeroing command or writing a command of zeroes
 *
 * (neither flag)  write zeroes punching a hole using an efficient
 *                 zeroing or fallback to writing zeroes manually.
 */
static void
fill_dst_range_with_zeroes (uint64_t offset, size_t length, void *buf)
{
  if (target_is_zero) return;

  /* Try efficient zeroing. */
  if (dst->ops->synch_zero (dst, offset, length, allocated))
    return;

  /* Fall back to loop writing zeroes. */
  memset (buf, 0, MIN (length, request_size));
  while (length > 0) {
    size_t len = MIN (length, request_size);

    dst->ops->synch_write (dst, buf, len, offset);
    length -= len;
    offset += len;
  }
}

void
synch_copying (void)
{
  uint64_t offset = 0;
  unsigned char *buf;

  buf = malloc (request_size);
  if (buf == NULL) {
    perror ("malloc");
    exit (EXIT_FAILURE);
  }

  /* If the source size is unknown then we copy data and cannot use
   * extent information.
   */
  if (src->size == -1) {
    size_t r;

    while ((r = src->ops->synch_read (src, buf, request_size, offset)) > 0) {
      update_blkhash ((const char *) buf, offset, r);
      dst->ops->synch_write (dst, buf, r, offset);
      offset += r;
      progress_bar (offset, src->size);
    }

    /* Record the total amount of data that was copied.  In all other
     * cases, src->size will already be set to the true size, so here
     * is the only place we have to set this.
     */
    src->size = offset;
  }

  /* Otherwise we know how much we're copying, so we can copy in whole
   * blocks and use extent information to optimize the case.
   */
  else {
    while (offset < src->size) {
      extent_list exts = empty_vector;
      uint64_t count = src->size - offset;
      size_t i, r;

      if (count > request_size)
        count = request_size;

      if (extents)
        src->ops->get_extents (src, 0, offset, count, &exts);
      else
        default_get_extents (src, 0, offset, count, &exts);

      for (i = 0; i < exts.len; ++i) {
        assert (exts.ptr[i].length <= count);

        if (exts.ptr[i].zero) {
          update_blkhash (NULL, offset, exts.ptr[i].length);
          fill_dst_range_with_zeroes(offset, exts.ptr[i].length, buf);
          offset += exts.ptr[i].length;
        }
        else /* data */ {
          r = src->ops->synch_read (src, buf, exts.ptr[i].length, offset);

          /* These cases should never happen unless the file is
           * truncated underneath us.
           */
          if (r == 0 || r < exts.ptr[i].length) {
            fprintf (stderr, "%s: unexpected end of file\n", src->name);
            exit (EXIT_FAILURE);
          }

          update_blkhash ((const char *) buf, offset, r);
          dst->ops->synch_write (dst, buf, r, offset);
          offset += r;
          progress_bar (offset, src->size);
        }
      }

      free (exts.ptr);
    } /* while */
  }

  free (buf);
}
