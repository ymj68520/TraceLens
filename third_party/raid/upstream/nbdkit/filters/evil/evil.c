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
#include <time.h>
#include <assert.h>

#include <nbdkit-filter.h>

#include "minmax.h"
#include "ispowerof2.h"
#include "random.h"

enum mode {
  COSMIC_RAYS,
  STUCK_BITS,
  STUCK_WIRES,
};
static const char *evil_mode_to_string (enum mode);

static enum mode evil_mode = STUCK_BITS;
static double evil_probability = -1; /* default depends on mode */
static double evil_stuck_probability = 1.0;
static uint32_t evil_seed;

/* Probabilities < ε are treated as zero to avoid both divide by zero
 * problems and potentially exploding values in calculations.
 */
#define EPSILON 1e-12

/* Probabilities > MAXP are treated as 100%.  This is because our
 * algorithm below can corrupt at most 1 bit per byte and doesn't make
 * progress otherwise.
 */
#define MAXP (1.0/8.0)

static void
evil_load (void)
{
  evil_seed = time (NULL);
}

static int
evil_config (nbdkit_next_config *next, nbdkit_backend *nxdata,
             const char *key, const char *value)
{
  if (strcmp (key, "evil") == 0 || strcmp (key, "evil-mode") == 0) {
    if (strcmp (value, "cosmic-rays") == 0 ||
        strcmp (value, "cosmic") == 0) {
      evil_mode = COSMIC_RAYS;
      return 0;
    }
    else if (strcmp (value, "stuck-bits") == 0 ||
             strcmp (value, "stuck-bit") == 0 ||
             strcmp (value, "stuck") == 0) {
      evil_mode = STUCK_BITS;
      return 0;
    }
    else if (strcmp (value, "stuck-wires") == 0 ||
             strcmp (value, "stuck-wire") == 0) {
      evil_mode = STUCK_WIRES;
      return 0;
    }
    else {
      nbdkit_error ("evil: unknown mode: %s", value);
      return -1;
    }
  }
  else if (strcmp (key, "evil-probability") == 0) {
    if (nbdkit_parse_probability ("evil-probability", value,
                                  &evil_probability) == -1)
      return -1;
    if (evil_probability > 1) {
      nbdkit_error ("%s: probability out of range, should be [0..1]", key);
      return -1;
    }
    return 0;
  }
  else if (strcmp (key, "evil-stuck-probability") == 0) {
    if (nbdkit_parse_probability ("evil-stuck-probability", value,
                                  &evil_stuck_probability) == -1)
      return -1;
    if (evil_stuck_probability > 1) {
      nbdkit_error ("%s: probability out of range, should be [0..1]", key);
      return -1;
    }
    return 0;
  }
  else if (strcmp (key, "evil-seed") == 0) {
    if (nbdkit_parse_uint32_t ("evil-seed", value, &evil_seed) == -1)
      return -1;
    return 0;
  }
  else
    return next (nxdata, key, value);
}

static int
evil_config_complete (nbdkit_next_config_complete *next,
                      nbdkit_backend *nxdata)
{
  if (evil_probability < 0) {
    /* Choose default probability based on the chosen mode. */
    switch (evil_mode) {
    case COSMIC_RAYS:
    case STUCK_BITS:
      evil_probability = 1e-8;
      break;
    case STUCK_WIRES:
      evil_probability = 1e-6;
    }
  }

  return next (nxdata);
}

#define evil_config_help \
  "evil=cosmic-rays|stuck-bits|stuck-wires\n" \
  "                               Set the mode (default: cosmic-rays).\n" \
  "evil-probability=PROB          Probability of flipped or stuck bit.\n" \
  "evil-seed=SEED                 Random number seed.\n" \
  "evil-stuck-probability=PROB    Probability of stuck bit being stuck."

/* This is the heart of the algorithm, the function which corrupts
 * the buffer after reading it from the plugin.
 *
 * The observation is that if we have a block of (eg) size 10**6 bits
 * and our probability of finding a corrupt bit is (eg) 1/10**4, then
 * we expect approximately 100 bits in the block to be corrupted.
 *
 * For stuck bits we want the corrupted bits to be the same on each
 * access, either relative to the backing disk (STUCK_BITS) or to the
 * request (STUCK_WIRES).
 *
 * Instead of creating an expensive bitmap ahead of time covering the
 * whole disk, we can use the random number generator with a fixed
 * seed derived from the offset of the start of the block.  We can
 * then choose a random number uniformly in the range [0..2*(1/P)) (in
 * the example [0..2*10**4)) as the distance to the next corrupt bit.
 * We jump forwards, corrupt that bit, and repeat until we reach the
 * end of the block.
 *
 * "Corrupted" in this case can mean flipped by cosmic rays or stuck,
 * depending on the filter mode.
 *
 * On average this will choose the right number of bits in the block.
 * (Although their distribution will be suboptimal.  In a uniform
 * distribution it should be possible for two corrupted bits to be
 * greater than 2*(1/P) apart, but the above algorithm would not do
 * this.  Also this algorithm cannot corrupt two bits in the same
 * byte.  In practice this probably doesn't matter as long as P is
 * small.)
 *
 * Note that "block" != "buffer", especially in the STUCK_BITS mode.
 * We iterate over blocks as above, but only corrupt a bit when it
 * happens to coincide with the buffer we have just read.
 *
 * We choose the block size adaptively so that at least 100 bits in
 * the block will be corrupted.  The block size must be a power of 2.
 * The block size thus depends on the probability.
 */
enum corruption_type { FLIP, STUCK };

static uint64_t block_size;     /* in bytes */
static struct random_state state; /* only used for cosmic-rays */

static int
evil_thread_model (int next_thread_model)
{
  switch (evil_mode) {
  case COSMIC_RAYS:
    /* Because cosmic-rays uses the global random state we need to
     * tighten the thread model.
     */
    return NBDKIT_THREAD_MODEL_SERIALIZE_REQUESTS;

  case STUCK_BITS:
  case STUCK_WIRES:
    return NBDKIT_THREAD_MODEL_PARALLEL;
  }
  abort ();
}

static int
evil_get_ready (int thread_model)
{
  switch (evil_mode) {
  case COSMIC_RAYS:
    xsrandom ((uint64_t) evil_seed, &state);
    break;

  case STUCK_BITS:
  case STUCK_WIRES:
    ;
  }

  /* Choose the block size based on the probability, so that at least
   * 100 bits are expected to be corrupted in the block.  Block size
   * must be a power of 2.
   *
   * Example: P = 1e-4
   *          => ideal block_size = 100 / 1e-4 = 1e6 (bits) = 1e6 / 8 (bytes)
   *          => next power of 2 block_size = 131072 = 2**17
   *          => expected bits per block = ~104
   */
  if (evil_probability < EPSILON || evil_probability > MAXP)
    block_size = 1024*1024;     /* unused so value doesn't matter */
  else
    block_size = next_power_of_2 ((uint64_t) (100. / evil_probability) / 8);

  nbdkit_debug ("evil: mode: %s, P: %lg, seed: %" PRIu32,
                evil_mode_to_string (evil_mode),
                evil_probability, evil_seed);
  nbdkit_debug ("evil: block_size: %" PRIu64 " (2**%d)",
                block_size, log_2_bits (block_size));
  nbdkit_debug ("evil: expected bits per block: %g",
                8 * block_size * evil_probability);

  return 0;
}

static void corrupt_all_bits (uint8_t *buf, uint32_t count,
                              struct random_state *rs,
                              enum corruption_type ct);
static uint8_t corrupt_one_bit (uint8_t byte, unsigned bit,
                                uint64_t rand, enum corruption_type ct);

static void
corrupt_buffer (uint8_t *buf, uint32_t count, uint64_t offset_in_block,
                struct random_state *rs, enum corruption_type ct)
{
  /* No corruption, and avoids a divide by zero below. */
  if (evil_probability < EPSILON) return;

  /* 100% corruption, avoids lack of progress in the loop below. */
  if (evil_probability > MAXP) {
    corrupt_all_bits (buf, count, rs, ct);
    return;
  }

  uint64_t offs, intvl, i, randnum;
  const uint64_t invp2 = (uint64_t) (2.0 / evil_probability);

  assert ((offset_in_block & ~(block_size-1)) == 0);

  /* Iterate over the whole block from the start. */
  for (offs = 0; offs < offset_in_block + count; ) {
    /* Choose the length of the interval to the next corrupted bit, by
     * picking a random number in [0..2*(1/P)].
     *
     * Remember this is in bits!
     */
    intvl = xrandom (rs) % invp2;

    /* Consume one more random state.  We may or may not use this.
     * But we need to always consume two random states per iteration
     * to make the output predictable.
     */
    randnum = xrandom (rs);

    /* Adjust offs to that byte. */
    offs += intvl / 8;

    /* If we have gone past the end of buffer, stop. */
    if (offs >= offset_in_block + count) break;

    /* If the current offs lies within the buffer, corrupt a bit. */
    if (offs >= offset_in_block) {
      i = offs - offset_in_block;
      assert (i < count);
      buf[i] = corrupt_one_bit (buf[i], intvl & 7, randnum, ct);
    }
  }
}

static void
corrupt_all_bits (uint8_t *buf, uint32_t count,
                  struct random_state *rs, enum corruption_type ct)
{
  size_t i;
  unsigned bit;
  uint8_t b;
  uint64_t randnum;

  /* This is used when MAXP < P <= 100%.  We treat it the same as 100%
   * and corrupt all bits.
   */
  for (i = 0; i < count; ++i) {
    b = buf[i];
    for (bit = 0; bit < 8; ++bit) {
      randnum = xrandom (rs);
      b = corrupt_one_bit (b, bit, randnum, ct);
    }
    buf[i] = b;
  }
}

static uint8_t
corrupt_one_bit (uint8_t byte, unsigned bit,
                 uint64_t randnum, enum corruption_type ct)
{
  const unsigned mask = 1 << bit;

  switch (ct) {
  case FLIP:
    byte ^= mask;
    break;
  case STUCK:
    randnum &= 0xffffffff;
    if (evil_stuck_probability * 0x100000000 > randnum) {
      if (randnum & 1) /* stuck high or low? */
        byte |= mask;
      else
        byte &= ~mask;
    }
  }
  return byte;
}

/* Read data. */
static int
evil_pread (nbdkit_next *next,
            void *handle, void *buf, uint32_t count, uint64_t offset,
            uint32_t flags, int *err)
{
  uint64_t seed, bstart, len;
  struct random_state local_state;

  if (next->pread (next, buf, count, offset, flags, err) == -1)
    return -1;

  switch (evil_mode) {
  case COSMIC_RAYS:
    /* Use the global random state because we want to flip bits at random. */
    corrupt_buffer (buf, count, 0, &state, FLIP);
    break;

  case STUCK_BITS:
    /* Split the request to align with blocks. */
    bstart = offset & ~(block_size-1);
    while (count > 0) {
      /* Set the seed so we corrupt the same bits relative to the offset. */
      seed = (int64_t) evil_seed + bstart;
      xsrandom (seed, &local_state);
      /* If the buffer straddles two blocks, shorten to just the part
       * inside the first block.
       */
      len = MIN (count, bstart + block_size - offset);
      corrupt_buffer (buf, len, offset - bstart, &local_state, STUCK);
      bstart += block_size;
      offset += len;
      buf += len;
      count -= len;
    }
    break;

  case STUCK_WIRES:
    /* Set the seed so we corrupt the same bits in every request. */
    seed = (int64_t) evil_seed;
    xsrandom (seed, &local_state);
    corrupt_buffer (buf, count, 0, &local_state, STUCK);
    break;
  }

  return 0;
}

static const char *
evil_mode_to_string (enum mode mode)
{
  switch (mode) {
  case COSMIC_RAYS: return "cosmic-rays";
  case STUCK_BITS:  return "stuck-bits";
  case STUCK_WIRES: return "stuck-wires";
  }
  abort ();
}

static struct nbdkit_filter filter = {
  .name              = "evil",
  .longname          = "nbdkit evil filter",
  .load              = evil_load,
  .config            = evil_config,
  .config_complete   = evil_config_complete,
  .config_help       = evil_config_help,
  .thread_model      = evil_thread_model,
  .get_ready         = evil_get_ready,
  .pread             = evil_pread,
};

NBDKIT_REGISTER_FILTER (filter)
