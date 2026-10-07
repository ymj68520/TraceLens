/* nbdkit
 * Copyright Red Hat
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met:
 *
 * * Redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer.
 *
 * * Redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution.
 *
 * * Neither the name of Red Hat nor the names of its contributors may be
 * used to endorse or promote products derived from this software without
 * specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY RED HAT AND CONTRIBUTORS ''AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
 * THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
 * PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL RED HAT OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
 * USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
 * OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 */

/* Unit tests of protocol strings. */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#undef NDEBUG /* Keep test strong even for nbdkit built without assertions */
#include <assert.h>

#include "nbd-protocol.h"
#include "protostrings.h"

#define TEST_GOOD(fn, val)                               \
  {                                                      \
    const char *actual = fn (val);                       \
    printf ("%d: %u -> %s\n", __LINE__, val, actual);    \
    assert (strcmp (actual, #val) == 0);                 \
  }
#define TEST_UNKNOWN(fn, val, expected)                 \
  {                                                     \
    const char *actual = fn (val);                      \
    printf ("%d: %u -> %s\n", __LINE__, val, actual);   \
    assert (strcmp (actual, expected) == 0);            \
  }

int
main (void)
{
  TEST_GOOD (name_of_nbd_cmd, NBD_CMD_READ);
  TEST_GOOD (name_of_nbd_cmd, NBD_CMD_DISC);
  TEST_UNKNOWN (name_of_nbd_cmd, 0x100, "unknown (0x100)");

  TEST_GOOD (name_of_nbd_cmd_flag, NBD_CMD_FLAG_FUA);
  TEST_UNKNOWN (name_of_nbd_cmd_flag, 0xffffff, "unknown (0xffffff)");

  TEST_GOOD (name_of_nbd_flag, NBD_FLAG_SEND_DF);
  TEST_GOOD (name_of_nbd_global_flag, NBD_FLAG_FIXED_NEWSTYLE);
  TEST_GOOD (name_of_nbd_info, NBD_INFO_EXPORT);
  TEST_GOOD (name_of_nbd_opt, NBD_OPT_ABORT);
  TEST_GOOD (name_of_nbd_rep, NBD_REP_INFO);
  TEST_GOOD (name_of_nbd_reply, NBD_REPLY_FLAG_DONE);
  TEST_GOOD (name_of_nbd_reply_type, NBD_REPLY_TYPE_ERROR);
  exit (EXIT_SUCCESS);
}
