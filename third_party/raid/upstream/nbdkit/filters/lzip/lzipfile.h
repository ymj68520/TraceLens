/* nbdkit lzip filter
 * Copyright Jan Felix Langenbach
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

#ifndef NBDKIT_LZIPFILE_H
#define NBDKIT_LZIPFILE_H

#include <nbdkit-filter.h>

typedef struct lzipfile lzipfile;

/* Open (and verify) the named lzip file. */
extern lzipfile *lzipfile_open (nbdkit_next *next);

/* Close the file and free up all resources. */
extern void lzipfile_close (lzipfile *);

/* Get (uncompressed) size of the largest block in the file. */
extern uint64_t lzipfile_max_uncompressed_block_size (lzipfile *);

/* Get the total uncompressed size of the file. */
extern uint64_t lzipfile_get_size (lzipfile *);

/* Read the lzip file block that contains the byte at 'offset' in the
 * uncompressed file.
 *
 * The uncompressed block of data, which probably begins before the
 * requested byte and ends after it, is returned.  The caller must
 * free it.  NULL is returned if there was an error.
 *
 * The start offset & size of the block relative to the uncompressed
 * file are returned in *start and *size.
 */
extern char *lzipfile_read_block (lzipfile *xz,
                                  nbdkit_next *next,
                                  uint32_t flags, int *err,
                                  uint64_t offset,
                                  uint64_t *start, uint64_t *size);


#endif /* NBDKIT_LZIPFILE_H */
