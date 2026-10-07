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
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <string.h>

#include "array-size.h"
#include "human-size.h"
#include "human-size-test-cases.h" /* defines 'pairs' below */

static unsigned errors = 0;

/* Test the human_size_parse function. */
static void
test1 (void)
{
  size_t i;

  for (i = 0; i < ARRAY_SIZE (pairs); i++) {
    const char *error = NULL, *pstr = NULL;
    int64_t r;

    r = human_size_parse (pairs[i].str, &error, &pstr);
    if (r != pairs[i].res) {
      fprintf (stderr,
               "Wrong parse for %s, got %" PRId64 ", expected %" PRId64 "\n",
               pairs[i].str, r, pairs[i].res);
      errors++;
    }
    if (r == -1) {
      if (error == NULL || pstr == NULL) {
        fprintf (stderr, "Wrong error message handling for %s\n", pairs[i].str);
        errors++;
      }
    }
  }
}

/* Test the human_size function. */
static void
test2_run (uint64_t bytes, const char *expected, bool expected_human_flag)
{
  char actual[HUMAN_SIZE_LONGEST];
  bool actual_human_flag;

  human_size (actual, bytes, &actual_human_flag);

  if (strcmp (actual, expected) == 0 &&
      actual_human_flag == expected_human_flag) {
    printf ("test-human-size: %" PRIu64 " -> \"%s\" (%s) OK\n",
            bytes, actual, actual_human_flag ? "true" : "false");
    fflush (stdout);
  }
  else {
    fprintf (stderr,
             "test-human-size: error: test case %" PRIu64 " "
             "expected \"%s\" (%s) "
             "but returned \"%s\" (%s)\n",
             bytes,
             expected, expected_human_flag ? "true" : "false",
             actual, actual_human_flag ? "true" : "false");
    errors++;
  }
}

static void
test2 (void)
{
  test2_run (0, "0", false);
  test2_run (1, "1", false);
  test2_run (512, "512", false);
  test2_run (1023, "1023", false);
  test2_run (1024, "1K", true);
  test2_run (1025, "1025", false);
  test2_run (2047, "2047", false);
  test2_run (2048, "2K", true);
  test2_run (3 * 1024, "3K", true);

  test2_run (1023 * 1024, "1023K", true);
  test2_run (1048575, "1048575", false);
  test2_run (1048576, "1M", true);
  test2_run (1048577, "1048577", false);

  test2_run (UINT64_C (1073741824), "1G", true);

  test2_run (UINT64_C (1099511627776), "1T", true);
  test2_run (UINT64_C (1099511627777), "1099511627777", false);
  test2_run (UINT64_C (1099511627776) + 1024, "1073741825K", true);

  test2_run (UINT64_C (1125899906842624), "1P", true);

  test2_run ((uint64_t)INT64_MAX+1, "8E", true);
  test2_run (UINT64_MAX-1023, "18014398509481983K", true);
  test2_run (UINT64_MAX, "18446744073709551615", false);
}

int
main (int argc, char *argv[])
{
  test1 ();
  test2 ();
  exit (errors == 0 ? EXIT_SUCCESS : EXIT_FAILURE);
}
