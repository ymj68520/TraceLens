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
#include <stdint.h>
#include <inttypes.h>
#include <assert.h>
#include <pthread.h>

#ifdef HAVE_GNUTLS
#include <gnutls/gnutls.h>
#include <gnutls/crypto.h>
#endif

#include <libnbd.h>

#include "byte-swapping.h"
#include "ispowerof2.h"
#include "iszero.h"
#include "minmax.h"
#include "rounding.h"
#include "vector.h"

#include "nbdcopy.h"

#ifdef HAVE_GNUTLS

/* unknown => We haven't seen this block yet.  'ptr' is NULL.
 *
 * zero => The block is all zeroes.  'ptr' is NULL.
 *
 * data => The block is all data, and we have seen the whole block,
 * and the hash has been computed.  'ptr' points to the computed
 * hash.  'n' is unused.
 *
 * incomplete => Part of the block was seen.  'ptr' points to the
 * data block, waiting to be completed.  'n' is the number of bytes
 * seen so far.  We will compute the hash and turn this into a
 * 'data' or 'zero' block, either when we have seen all bytes of
 * this block, or at the end.
 *
 * Note that this code assumes that we are called exactly once for a
 * range in the disk image.
 */
enum block_type { block_unknown = 0, block_zero, block_data, block_incomplete };

/* We will have one of these structs per blkhash block. */
struct block {
  void *ptr;
  uint32_t n;
  enum block_type type;
};

DEFINE_VECTOR_TYPE(blocks, struct block);
static blocks block_vec;

static void
free_struct_block (struct block b)
{
  free (b.ptr);
}

/* Since nbdcopy is multi-threaded, we need to use locks to protect
 * access to shared resources.  But also because computing digests is
 * very compute intensive, we must allow those to run in parallel as
 * much as possible.  Therefore the locking is carefully chosen to
 * protect critical resources while allowing (most) hashing to happen
 * in parallel.
 *
 * 'bv_lock' protects access to 'block_vec', and is needed whenever
 * the vector might be extended.
 *
 * It's safe to hash complete blocks without acquiring any lock (since
 * we should only be called once per complete block).  However
 * 'incomplete_lock' must be acquired whenever we deal with incomplete
 * blocks as we might be called in parallel for those.
 */
static pthread_mutex_t bv_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t incomplete_lock = PTHREAD_MUTEX_INITIALIZER;

/* Length of the digests of this algorithm in bytes. */
static size_t alg_len;

void
init_blkhash (void)
{
  if (blkhash_alg == GNUTLS_DIG_UNKNOWN) return;

  assert (is_power_of_2 (blkhash_size));

  alg_len = gnutls_hash_get_len (blkhash_alg);

  /* If we know the source size in advance, reserve the block vector.
   * We don't always know this (src->size == -1), eg. if reading from
   * a pipe.  If the size is exactly zero we don't need to reserve
   * anything.
   */
  if (src->size > 0) {
    if (blocks_reserve_exactly (&block_vec,
                                DIV_ROUND_UP (src->size, blkhash_size)) == -1) {
      perror ("nbdcopy: realloc");
      exit (EXIT_FAILURE);
    }
  }
}

/* Single block update functions. */
static struct block
get_block (uint64_t blknum)
{
  struct block b;

  pthread_mutex_lock (&bv_lock);

  /* Grow the underlying storage if needed. */
  if (block_vec.cap <= blknum) {
    if (blocks_reserve (&block_vec, blknum - block_vec.len + 1) == -1) {
      perror ("nbdcopy: realloc");
      exit (EXIT_FAILURE);
    }
  }

  /* Initialize new blocks if needed. */
  if (block_vec.len <= blknum) {
    size_t i;
    for (i = block_vec.len; i <= blknum; ++i) {
      block_vec.ptr[i].type = block_unknown;
      block_vec.ptr[i].ptr = NULL;
      block_vec.ptr[i].n = 0;
    }
    block_vec.len = blknum+1;
  }

  b = block_vec.ptr[blknum];

  pthread_mutex_unlock (&bv_lock);

  return b;
}

static void
put_block (uint64_t blknum, struct block b)
{
  pthread_mutex_lock (&bv_lock);
  block_vec.ptr[blknum] = b;
  pthread_mutex_unlock (&bv_lock);
}

/* Compute the hash of a single block of data and return it.  This is
 * normally a full block of size blkhash_size, but may be a smaller
 * block at the end of the file.
 */
static void *
compute_one_block_hash (const void *buf, size_t len)
{
  gnutls_hash_hd_t dig;
  int r;
  void *digest;

  /* Create the digest handle. */
  r = gnutls_hash_init (&dig, blkhash_alg);
  if (r < 0) {
    fprintf (stderr, "nbdcopy: gnutls_hash_init: %s\n", gnutls_strerror (r));
    exit (EXIT_FAILURE);
  }

  /* Allocate space for the result. */
  digest = malloc (alg_len);
  if (digest == NULL) {
    perror ("nbdcopy: malloc");
    exit (EXIT_FAILURE);
  }

  r = gnutls_hash (dig, buf, len);
  if (r < 0) {
    fprintf (stderr, "nbdcopy: gnutls_hash: %s\n", gnutls_strerror (r));
    exit (EXIT_FAILURE);
  }

  gnutls_hash_deinit (dig, digest);
  return digest; /* caller must free */
}

/* We have received a complete block.  Compute the hash for this
 * block.  If buf == NULL, sets the block to zero.  Note this function
 * assumes we can only be called once per complete block, so locking
 * is unnecessary (apart from inside the calls to get/put_block).
 */
static void
set_complete_block (uint64_t blknum, const char *buf)
{
  struct block b = get_block (blknum);
  void *p;

  /* Assert that we haven't seen this block before. */
  assert (b.type == block_unknown);

  /* Detecting a zero block is 20-100 times faster than computing a hash
   * depending on the machine and the algorithm.
   */
  if (buf && !is_zero (buf, blkhash_size)) {
    b.type = block_data;

    /* Compute the hash of the whole block now. */
    p = compute_one_block_hash (buf, blkhash_size);
    b.ptr = p;
  }
  else {
    b.type = block_zero;
    /* Hash is computed for all zero blocks in one go at the end. */
  }

  put_block (blknum, b);
}

static void finish_block (struct block *b);

/* We have received a partial block.  Store or update what we have.
 * If this completes the block, then do what is needed.  If buf ==
 * NULL, this is a partial zero instead.
 */
static void
set_incomplete_block (uint64_t blknum,
                      uint64_t blkoffs, uint64_t len,
                      const char *buf)
{
  /* We must acquire the incomplete_lock here, see locking comment above. */
  pthread_mutex_lock (&incomplete_lock);

  struct block b = get_block (blknum);

  switch (b.type) {
  case block_data:
  case block_zero:
    /* We shouldn't have seen the complete block before. */
    abort ();

  case block_unknown:
    /* Allocate the block. */
    b.ptr = calloc (1, blkhash_size);
    if (b.ptr == NULL) {
      perror ("nbdcopy: calloc");
      exit (EXIT_FAILURE);
    }
    b.n = 0;
    b.type = block_incomplete;

    /*FALLTHROUGH*/
  case block_incomplete:
    if (buf)
      /* Add the partial data to the block. */
      memcpy ((char *)b.ptr + blkoffs, buf, len);
    else
      /* Add the partial zeroes to the block. */
      memset ((char *)b.ptr + blkoffs, 0, len);
    b.n += len;

    /* If the block is now complete, finish it off. */
    if (b.n == blkhash_size)
      finish_block (&b);

    put_block (blknum, b);
  }

  pthread_mutex_unlock (&incomplete_lock);
}

static void
finish_block (struct block *b)
{
  void *p;

  assert (b->type == block_incomplete);

  if (b->n == blkhash_size && is_zero (b->ptr, blkhash_size)) {
    b->type = block_zero;
    free (b->ptr);
    b->ptr = NULL;
  }
  else {
    b->type = block_data;
    /* Compute the hash of the block. */
    p = compute_one_block_hash (b->ptr, b->n);
    free (b->ptr);
    b->ptr = p;
  }
}

/* Called from either synch-copying.c or multi-thread-copying.c to
 * update the hash with some data (or zero if buf == NULL).
 */
void
update_blkhash (const char *buf, uint64_t offset, size_t len)
{
  uint64_t blknum, blkoffs;

  if (blkhash_alg == GNUTLS_DIG_UNKNOWN) return;

  if (verbose) {
    fprintf (stderr, "blkhash: %s "
             "[0x%" PRIx64 " - 0x%" PRIx64 "] (length %zu)\n",
             buf ? "data" : "zero",
             offset, offset+len, len);
  }

  /* Iterate over the blocks. */
  blknum = offset / blkhash_size;
  blkoffs = offset % blkhash_size;

  /* Unaligned head */
  if (blkoffs) {
    uint64_t n = MIN (blkhash_size - blkoffs, len);
    set_incomplete_block (blknum, blkoffs, n, buf);
    if (buf) buf += n;
    len -= n;
    offset += n;
    blknum++;
  }

  /* Aligned body */
  while (len >= blkhash_size) {
    set_complete_block (blknum, buf);
    if (buf) buf += blkhash_size;
    len -= blkhash_size;
    offset += blkhash_size;
    blknum++;
  }

  /* Unaligned tail */
  if (len) {
    set_incomplete_block (blknum, 0, len, buf);
  }
}

/* Called after copying to finish and print the resulting blkhash. */
void
finish_blkhash (uint64_t total_size)
{
  gnutls_hash_hd_t dig;
  size_t i;
  struct block *b;
  void *zero_block;
  void *zero_digest;
  int r;
  const uint64_t total_size_le = htole64 (total_size);
  unsigned char *final_digest;
  FILE *fp;

  if (blkhash_alg == GNUTLS_DIG_UNKNOWN) return;

  if (verbose) {
    fprintf (stderr, "blkhash: total size 0x%" PRIx64 "\n", total_size);
    fprintf (stderr, "blkhash: number of blocks %zu\n", block_vec.len);
  }

  /* If the last block is incomplete, finish it. */
  if (block_vec.len > 0) {
    b = &block_vec.ptr[block_vec.len-1];
    if (b->type == block_incomplete)
      finish_block (b);
  }

  /* There must be no other unknown or incomplete blocks left. */
  for (i = 0; i < block_vec.len; ++i) {
    b = &block_vec.ptr[i];
    assert (b->type != block_unknown);
    assert (b->type != block_incomplete);
  }

  /* Calculate the hash of a zero block. */
  zero_block = calloc (1, blkhash_size);
  if (zero_block == NULL) {
    perror ("nbdcopy: calloc");
    exit (EXIT_FAILURE);
  }
  zero_digest = compute_one_block_hash (zero_block, blkhash_size);
  free (zero_block);

  /* Now compute the blkhash. */
  r = gnutls_hash_init (&dig, blkhash_alg);
  if (r < 0) {
    fprintf (stderr, "nbdcopy: gnutls_hash_init: %s\n", gnutls_strerror (r));
    exit (EXIT_FAILURE);
  }

  for (i = 0; i < block_vec.len; ++i) {
    b = &block_vec.ptr[i];

    switch (b->type) {
    case block_unknown:
    case block_incomplete:
      abort (); /* see assertion above */

    case block_data:
      /* Mix in the block digest. */
      r = gnutls_hash (dig, b->ptr, alg_len);
      if (r < 0) {
        fprintf (stderr, "nbdcopy: gnutls_hash: %s\n", gnutls_strerror (r));
        exit (EXIT_FAILURE);
      }
      break;

    case block_zero:
      /* Block is zero, mix in the zero digest. */
      r = gnutls_hash (dig, zero_digest, alg_len);
      if (r < 0) {
        fprintf (stderr, "nbdcopy: gnutls_hash: %s\n", gnutls_strerror (r));
        exit (EXIT_FAILURE);
      }
      break;
    }
  }

  free (zero_digest);

  /* Append the length at the end. */
  r = gnutls_hash (dig, &total_size_le, sizeof total_size_le);
  if (r < 0) {
    fprintf (stderr, "nbdcopy: gnutls_hash: %s\n", gnutls_strerror (r));
    exit (EXIT_FAILURE);
  }

  /* Get the final digest. */
  final_digest = malloc (alg_len);
  if (final_digest == NULL) {
    perror ("nbdcopy: malloc");
    exit (EXIT_FAILURE);
  }

  gnutls_hash_deinit (dig, final_digest);

  /* Print the final digest. */
  if (blkhash_file != NULL) {
    fp = fopen (blkhash_file, "w");
    if (fp == NULL) {
      perror (blkhash_file);
      exit (EXIT_FAILURE);
    }
  }
  else {
    fp = stdout;
  }
  for (i = 0; i < alg_len; ++i)
    fprintf (fp, "%02x", final_digest[i]);
  fprintf (fp, "\n");
  fflush (fp);
  if (blkhash_file != NULL)
    fclose (fp);

  free (final_digest);

  /* Free the hashes and vector. */
  blocks_iter (&block_vec, free_struct_block);
  blocks_reset (&block_vec);
}

#else /* !HAVE_GNUTLS */

void
init_blkhash (void)
{
  /* nothing */
}

void
update_blkhash (const char *buf, uint64_t offset, size_t len)
{
  /* nothing */
}

void
finish_blkhash (uint64_t total_size)
{
  /* nothing */
}

#endif /* !HAVE_GNUTLS */
