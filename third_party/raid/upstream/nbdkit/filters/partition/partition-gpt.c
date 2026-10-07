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

#include <nbdkit-filter.h>

#include "byte-swapping.h"
#include "gpt.h"

#include "partition.h"

static int
get_gpt_header (uint8_t *sector,
                uint32_t *nr_partition_entries,
                uint32_t *size_partition_entry)
{
  struct gpt_header *header = (struct gpt_header *) sector;
  *nr_partition_entries = le32toh (header->nr_partition_entries);
  *size_partition_entry = le32toh (header->size_partition_entry);

  /* Many things are not checked here, but in particular, previously
   * written code has always needed partition_entries_lba to equal 2
   * because the original logic assumed the partition entries followed
   * the header, rather than looking in the header to see what LBA
   * they actually start at.  Let's at least check for that now.
   */
  if (le64toh (header->partition_entries_lba) != 2) {
    nbdkit_error ("non-standard GPT layout: "
                  "partition entries are not adjacent to header");
    return -1;
  }
  return 0;
}

static void
get_gpt_partition (uint8_t *bytes,
                   uint8_t *partition_type_guid,
                   uint64_t *first_lba, uint64_t *last_lba)
{
  struct gpt_entry *entry = (struct gpt_entry *) bytes;
  memcpy (partition_type_guid, entry->partition_type_guid, 16);
  *first_lba = le64toh (entry->first_lba);
  *last_lba = le64toh (entry->last_lba);
}

int
find_gpt_partition (nbdkit_next *next,
                    int64_t size, uint8_t *header_bytes,
                    int64_t *offset_r, int64_t *range_r)
{
  uint8_t partition_entry_sector[SECTOR_SIZE_4K]; /* May only use 512 bytes */
  uint8_t *partition_bytes;
  uint32_t nr_partition_entries, size_partition_entry, entries_per_sector;
  uint8_t partition_type_guid[16];
  uint64_t first_lba, last_lba;
  int i;
  int err;

  if (get_gpt_header (header_bytes,
                      &nr_partition_entries, &size_partition_entry) == -1)
    return -1;

  if (partnum > nr_partition_entries) {
    nbdkit_error ("GPT partition number out of range");
    return -1;
  }

  if (size_partition_entry < 128 || size_partition_entry > sector_size ||
      sector_size % size_partition_entry != 0) {
    nbdkit_error ("GPT partition entry size is invalid (%d bytes)",
      size_partition_entry);
    return -1;
  }

  /* Check the disk is large enough to contain the partition table
   * array (twice) plus other GPT overheads.  Otherwise it is likely
   * that the GPT header is bogus.
   */
  if (size < INT64_C (3) * sector_size +
      INT64_C (2) * nr_partition_entries * size_partition_entry) {
    nbdkit_error ("GPT partition table is too large for this disk");
    return -1;
  }

  entries_per_sector = sector_size / size_partition_entry;

  for (i = 0; i < nr_partition_entries; ++i) {
    /* We already checked these are within bounds above. */
    if (i % entries_per_sector == 0) {
      if (next->pread (next, partition_entry_sector, sector_size,
                       sector_size * (2 + i / entries_per_sector), 0,
                       &err) == -1)
        return -1;
    }
    partition_bytes =
      &partition_entry_sector[(i % entries_per_sector) * size_partition_entry];
    get_gpt_partition (partition_bytes,
                       partition_type_guid, &first_lba, &last_lba);
    if (memcmp (partition_type_guid,
                "\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0", 16) != 0 &&
        partnum == i+1) {
      *offset_r = first_lba * sector_size;
      *range_r = (1 + last_lba - first_lba) * sector_size;
      return 0;
    }
  }

  nbdkit_error ("GPT partition %d not found", partnum);
  return -1;
}
