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

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#undef NDEBUG /* Keep test strong even for nbdkit built without assertions */
#include <assert.h>

#include "ispowerof2.h"

int
main (void)
{
  uint64_t i;

  assert (! is_power_of_2 (0));

  /* is_power_of_2 is only defined for unsigned long type, which is
   * 32 bit on 32 bit platforms.  We need to store i in a 64 bit type
   * so the loops don't wrap around.
   */
  for (i = 1; i <= 0x80000000; i <<= 1)
    assert (is_power_of_2 (i));

  for (i = 4; i <= 0x80000000; i <<= 1)
    assert (! is_power_of_2 (i-1));

  /* Check log_2_bits on some known values. */
  assert (log_2_bits (1) == 0);
  assert (log_2_bits (512) == 9);
  assert (log_2_bits (4096) == 12);
  assert (log_2_bits (0x80000000) == 31);
  assert (log_2_bits (UINT64_C (0x100000000)) == 32);
  assert (log_2_bits (UINT64_C (0x8000000000000000)) == 63);

  /* Test next power of 2. */
  assert (next_power_of_2 (0) == 1);
  assert (next_power_of_2 (1) == 1);
  assert (next_power_of_2 (3) == 4);
  assert (next_power_of_2 (8) == 8);
  assert (next_power_of_2 (9) == 16);
  assert (next_power_of_2 (0xffff) == 0x10000);
  assert (next_power_of_2 (0x10000) == 0x10000);
  assert (next_power_of_2 (INT64_C ( 0xffffffff)) == 0x100000000);
  assert (next_power_of_2 (INT64_C (0x100000000)) == 0x100000000);
  assert (next_power_of_2 (INT64_C (0x200000001)) == 0x400000000);
  assert (next_power_of_2 (INT64_C (0x6ffffffff)) == 0x800000000);
  assert (next_power_of_2 (INT64_C (0x700000001)) == 0x800000000);
  assert (next_power_of_2 (INT64_C (0x800000000)) == 0x800000000);
  assert (next_power_of_2 (UINT64_C (0x8000000000000000)) ==
          UINT64_C (0x8000000000000000));
  assert (next_power_of_2 (-1) == (uint64_t)-1);

  exit (EXIT_SUCCESS);
}
