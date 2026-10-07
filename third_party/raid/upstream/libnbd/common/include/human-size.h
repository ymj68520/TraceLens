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

#ifndef NBDKIT_HUMAN_SIZE_H
#define NBDKIT_HUMAN_SIZE_H

#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <errno.h>

/* Attempt to parse a string with a possible scaling suffix, such as
 * "2M".  Disk sizes cannot usefully exceed off_t (which is signed)
 * and cannot be negative.
 *
 * On error, returns -1 and sets *error and *pstr.  You can form a
 * final error message by appending "<error>: <pstr>".
 */
static inline int64_t
human_size_parse (const char *str,
                  const char **error, const char **pstr)
{
  int64_t size;
  char *end;
  uint64_t scale = 1;

  /* XXX Should we also parse things like '1.5M'? */
  /* XXX Should we allow hex? If so, hex cannot use scaling suffixes,
   * because some of them are valid hex digits.
   */
  errno = 0;
  size = strtoimax (str, &end, 10);
  if (str == end) {
    *error = "could not parse size string";
    *pstr = str;
    return -1;
  }
  if (size < 0) {
    *error = "size cannot be negative";
    *pstr = str;
    return -1;
  }
  if (errno) {
    *error = "size exceeds maximum value";
    *pstr = str;
    return -1;
  }

  switch (*end) {
    /* No suffix */
  case '\0':
    end--; /* Safe, since we already filtered out empty string */
    break;

    /* Powers of 1024 */
  case 'e': case 'E':
    scale *= 1024;
    /* fallthru */
  case 'p': case 'P':
    scale *= 1024;
    /* fallthru */
  case 't': case 'T':
    scale *= 1024;
    /* fallthru */
  case 'g': case 'G':
    scale *= 1024;
    /* fallthru */
  case 'm': case 'M':
    scale *= 1024;
    /* fallthru */
  case 'k': case 'K':
    scale *= 1024;
    /* fallthru */
  case 'b': case 'B':
    break;

    /* "sectors", ie. units of 512 bytes, even if that's not the real
     * sector size
     */
  case 's': case 'S':
    scale = 512;
    break;

  default:
    *error = "could not parse size: unknown suffix";
    *pstr = end;
    return -1;
  }

  /* XXX Maybe we should support 'MiB' as a synonym for 'M'; and 'MB'
   * for powers of 1000, for similarity to GNU tools. But for now,
   * anything beyond 'M' is dropped.
   */
  if (end[1]) {
    *error = "could not parse size: unknown suffix";
    *pstr = end;
    return -1;
  }

  if (INT64_MAX / scale < size) {
    *error = "could not parse size: size * scale overflows";
    *pstr = str;
    return -1;
  }

  return size * scale;
}

/* If you allocate a buffer of at least this length in bytes and pass
 * it as the first parameter to human_size, then it will not overrun.
 */
#define HUMAN_SIZE_LONGEST 64

/* Convert bytes to a human-readable string.
 *
 * This is roughly the opposite of nbdkit_parse_size.  It will convert
 * multiples of powers of 1024 to the appropriate human size with the
 * right extension like 'M' or 'G'.  Anything that cannot be converted
 * is returned as bytes.  The *human flag is set to true if the output
 * was abbreviated to a human-readable size, or false if it is just
 * bytes.
 *
 * If buf == NULL, a buffer is allocated and returned.  In this case
 * the returned buffer must be freed.
 *
 * buf may also be allocated by the caller, in which case it must be
 * at least HUMAN_SIZE_LONGEST bytes.
 *
 * On error the function returns an error and sets errno.
 */
static inline char *
human_size (char *buf, uint64_t bytes, bool *human)
{
  static const char ext[] = "EPTGMK";
  size_t i;

  if (buf == NULL) {
    buf = malloc (HUMAN_SIZE_LONGEST);
    if (buf == NULL)
      return NULL;
  }

  /* Work out which extension to use, if any. */
  i = 6;
  while (bytes && (bytes & 1023) == 0) {
    bytes >>= 10;
    i--;
  }

  /* Set the flag to true if we're going to add a human-readable extension. */
  if (human)
    *human = ext[i] != '\0';

  snprintf (buf, HUMAN_SIZE_LONGEST, "%" PRIu64 "%.1s", bytes, &ext[i]);
  return buf;
}

#endif /* NBDKIT_HUMAN_SIZE_H */
