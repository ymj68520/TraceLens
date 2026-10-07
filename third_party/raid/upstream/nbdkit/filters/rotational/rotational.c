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
#include <string.h>

#include <nbdkit-filter.h>

static int rotational = 1;

static int
rotational_config (nbdkit_next_config *next, nbdkit_backend *nxdata,
                   const char *key, const char *value)
{
  int r;

  if (strcmp (key, "rotational") == 0) {
    r = nbdkit_parse_bool (value);
    if (r == -1)
      return -1;
    rotational = r;
    return 0;
  }

  else
    return next (nxdata, key, value);
}

#define rotational_config_help \
  "rotational=true|false   Set the rotational property (default: true)"

static int
rotational_is_rotational (nbdkit_next *next, void *handle)
{
  return rotational;
}

static struct nbdkit_filter filter = {
  .name              = "rotational",
  .longname          = "nbdkit rotational filter",
  .config            = rotational_config,
  .config_help       = rotational_config_help,
  .is_rotational     = rotational_is_rotational,
};

NBDKIT_REGISTER_FILTER (filter)
