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
#include <string.h>
#include <assert.h>

#include "array-size.h"
#include "human-size.h"
#include "human-size-test-cases.h" /* defines 'tuples' below */

int
main (void)
{
  size_t i;
  bool pass = true;

  for (i = 0; i < ARRAY_SIZE (tuples); i++) {
    const char *error = NULL, *pstr = NULL;
    char *rest = NULL;
    int64_t r;
    int64_t expect;

    r = human_size_parse (tuples[i].str, &error, &pstr);
    expect = tuples[i].tail && *tuples[i].tail ? -1 : tuples[i].res;
    if (r != expect) {
      fprintf (stderr,
               "Wrong parse for '%s', got %" PRId64 ", expected %" PRId64 "\n",
               tuples[i].str, r, expect);
      pass = false;
    }
    if (r == -1) {
      if (error == NULL || pstr == NULL) {
        fprintf (stderr, "Wrong error message handling for '%s'\n",
                 tuples[i].str);
        pass = false;
      }
    }

    r = human_size_parse_substr (tuples[i].str, &rest, &error, &pstr);
    if (r != tuples[i].res) {
      fprintf (stderr,
               "Wrong parse for '%s', got %" PRId64 ", expected %" PRId64 "\n",
               tuples[i].str, r, tuples[i].res);
      pass = false;
    }
    if (r == -1) {
      if (error == NULL || pstr == NULL) {
        /* Work around https://gcc.gnu.org/bugzilla/show_bug.cgi?id=120526 */
        assert (tuples[i].str);
        fprintf (stderr, "Wrong error message handling for '%s'\n",
                 tuples[i].str);
        pass = false;
      }
      if (rest != NULL) {
        fprintf (stderr,
                 "Wrong suffix handling for '%s', expected NULL, got '%s'\n",
                 tuples[i].str, rest);
        pass = false;
      }
    }
    else {
      if (rest == NULL) {
        fprintf (stderr,
                 "Wrong suffix handling for '%s', expected '%s', got NULL\n",
                 tuples[i].str, tuples[i].tail);
        pass = false;
      }
      else if (strcmp (rest, tuples[i].tail) != 0) {
        fprintf (stderr,
                 "Wrong suffix handling for '%s', expected '%s', got '%s'\n",
                 tuples[i].str, tuples[i].tail, rest);
        pass = false;
      }
    }
  }

  exit (pass ? EXIT_SUCCESS : EXIT_FAILURE);
}
