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
#include <time.h>

#include <pthread.h>

#define NBDKIT_API_VERSION 2
#include <nbdkit-plugin.h>

#include "cleanup.h"
#include "minmax.h"
#include "rounding.h"
#include "vector.h"

#include "vddk.h"

const char *
command_type_string (enum command_type type)
{
  switch (type) {
  case INFO:        return "info";
  case READ:        return "read";
  case WRITE:       return "write";
  case FLUSH:       return "flush";
  case CAN_EXTENTS: return "can_extents";
  case EXTENTS:     return "extents";
  case STOP:        return "stop";
  default:          abort ();
  }
}

/* Send command to the background thread and wait for completion.
 *
 * Returns 0 for OK
 * On error, calls nbdkit_error and returns -1.
 */
int
send_command_and_wait (struct vddk_handle *h, struct command *cmd)
{
  /* Add the command to the command queue. */
  {
    ACQUIRE_LOCK_FOR_CURRENT_SCOPE (&h->commands_lock);
    cmd->id = h->id++;

    if (command_queue_append (&h->commands, cmd) == -1)
      /* On error command_queue_append will call nbdkit_error. */
      return -1;

    /* Signal the caller if it could be sleeping on an empty queue. */
    if (h->commands.len == 1)
      pthread_cond_signal (&h->commands_cond);

    /* This will be used to signal command completion back to us. */
    pthread_mutex_init (&cmd->mutex, NULL);
    pthread_cond_init (&cmd->cond, NULL);
  }

  /* Wait for the command to be completed by the background thread. */
  {
    ACQUIRE_LOCK_FOR_CURRENT_SCOPE (&cmd->mutex);
    while (cmd->status == SUBMITTED)
      pthread_cond_wait (&cmd->cond, &cmd->mutex);
  }

  pthread_mutex_destroy (&cmd->mutex);
  pthread_cond_destroy (&cmd->cond);

  /* On error the background thread will call nbdkit_error. */
  switch (cmd->status) {
  case SUCCEEDED: return 0;
  case FAILED:    return -1;
  default:        abort ();
  }
}

/* Asynchronous commands are completed when this function is called. */
static void
complete_command (void *vp, VixError result)
{
  struct command *cmd = vp;

  if (vddk_debug_datapath)
    nbdkit_debug ("command %" PRIu64 " (%s) completed",
                  cmd->id, command_type_string (cmd->type));

  /* Update the stats for this asynchronous call. */
  update_stats (&cmd->start_t, cmd->count,
                cmd->type == READ ? &stats_VixDiskLib_ReadAsync :
                &stats_VixDiskLib_WriteAsync);

  ACQUIRE_LOCK_FOR_CURRENT_SCOPE (&cmd->mutex);

  if (result == VIX_OK) {
    cmd->status = SUCCEEDED;
  } else {
    VDDK_ERROR (result, "command %" PRIu64 ": asynchronous %s failed",
                cmd->id, command_type_string (cmd->type));
    cmd->status = FAILED;
  }

  pthread_cond_signal (&cmd->cond);
}

/* Wait for any asynchronous commands to complete. */
static int
do_stop (struct command *cmd, struct vddk_handle *h)
{
  VixError err;

  /* Because we assume VDDK >= 6.5, VixDiskLib_Wait must exist. */
  VDDK_CALL_START (VixDiskLib_Wait, "handle")
    err = VixDiskLib_Wait (h->handle);
  VDDK_CALL_END (VixDiskLib_Wait, 0);
  if (err != VIX_OK) {
    VDDK_ERROR (err, "VixDiskLib_Wait");
    /* In the end this error indication is ignored because it only
     * happens on the close path when we cannot handle errors.
     */
    return -1;
  }
  return 0;
}

/* Disk info command. */
static int64_t
do_info (struct command *cmd, struct vddk_handle *h)
{
  VixError err;
  VixDiskLibInfo **info = cmd->ptr;

  VDDK_CALL_START (VixDiskLib_GetInfo, "handle, info")
    err = VixDiskLib_GetInfo (h->handle, info);
  VDDK_CALL_END (VixDiskLib_GetInfo, 0);
  if (err != VIX_OK) {
    VDDK_ERROR (err, "VixDiskLib_GetInfo");
    return -1;
  }

  if (vddk_debug_diskinfo) {
    nbdkit_debug ("disk info: capacity: %" PRIu64 " sectors",
                  (*info)->capacity);
    nbdkit_debug ("disk info: biosGeo: C:%" PRIu32 " H:%" PRIu32 " S:%" PRIu32,
                  (*info)->biosGeo.cylinders,
                  (*info)->biosGeo.heads,
                  (*info)->biosGeo.sectors);
    nbdkit_debug ("disk info: physGeo: C:%" PRIu32 " H:%" PRIu32 " S:%" PRIu32,
                  (*info)->physGeo.cylinders,
                  (*info)->physGeo.heads,
                  (*info)->physGeo.sectors);
    nbdkit_debug ("disk info: adapter type: %d",
                  (int) (*info)->adapterType);
    nbdkit_debug ("disk info: num links: %d", (*info)->numLinks);
    nbdkit_debug ("disk info: parent filename hint: %s",
                  (*info)->parentFileNameHint ? : "NULL");
    nbdkit_debug ("disk info: uuid: %s",
                  (*info)->uuid ? : "NULL");
    if (library_version >= 7) {
      nbdkit_debug ("disk info: sector size: "
                    "logical %" PRIu32 " physical %" PRIu32,
                    (*info)->logicalSectorSize,
                    (*info)->physicalSectorSize);
    }
  }

  return 0;
}

static int
do_read (struct command *cmd, struct vddk_handle *h)
{
  VixError err;
  uint32_t count = cmd->count;
  uint64_t offset = cmd->offset;
  void *buf = cmd->ptr;

  /* Align to sectors. */
  if (!IS_ALIGNED (offset, VIXDISKLIB_SECTOR_SIZE)) {
    nbdkit_error ("%s is not aligned to sectors", "read");
    errno = EINVAL;
    return -1;
  }
  if (!IS_ALIGNED (count, VIXDISKLIB_SECTOR_SIZE)) {
    nbdkit_error ("%s is not aligned to sectors", "read");
    errno = EINVAL;
    return -1;
  }
  offset /= VIXDISKLIB_SECTOR_SIZE;
  count /= VIXDISKLIB_SECTOR_SIZE;

  gettimeofday (&cmd->start_t, NULL);

  VDDK_CALL_START (VixDiskLib_ReadAsync,
                   "handle, %" PRIu64 " sectors, "
                   "%" PRIu32 " sectors, buffer, callback, %" PRIu64,
                   offset, count, cmd->id)
    err = VixDiskLib_ReadAsync (h->handle, offset, count, buf,
                                complete_command, cmd);
  VDDK_CALL_END_ASYNC ();
  if (err != VIX_ASYNC) {
    VDDK_ERROR (err, "VixDiskLib_ReadAsync");
    return -1;
  }

  return 0;
}

static int
do_write (struct command *cmd, struct vddk_handle *h)
{
  VixError err;
  uint32_t count = cmd->count;
  uint64_t offset = cmd->offset;
  const void *buf = cmd->ptr;

  /* Align to sectors. */
  if (!IS_ALIGNED (offset, VIXDISKLIB_SECTOR_SIZE)) {
    nbdkit_error ("%s is not aligned to sectors", "write");
    errno = EINVAL;
    return -1;
  }
  if (!IS_ALIGNED (count, VIXDISKLIB_SECTOR_SIZE)) {
    nbdkit_error ("%s is not aligned to sectors", "write");
    errno = EINVAL;
    return -1;
  }
  offset /= VIXDISKLIB_SECTOR_SIZE;
  count /= VIXDISKLIB_SECTOR_SIZE;

  gettimeofday (&cmd->start_t, NULL);

  VDDK_CALL_START (VixDiskLib_WriteAsync,
                   "handle, %" PRIu64 " sectors, "
                   "%" PRIu32 " sectors, buffer, callback, %" PRIu64,
                   offset, count, cmd->id)
    err = VixDiskLib_WriteAsync (h->handle, offset, count, buf,
                                 complete_command, cmd);
  VDDK_CALL_END_ASYNC ();
  if (err != VIX_ASYNC) {
    VDDK_ERROR (err, "VixDiskLib_WriteAsync");
    return -1;
  }

  return 0;
}

static int
do_flush (struct command *cmd, struct vddk_handle *h)
{
  VixError err;

  /* It seems safer to wait for outstanding asynchronous commands to
   * complete before doing a flush, so do this but ignore errors
   * except to print them.
   */
  VDDK_CALL_START (VixDiskLib_Wait, "handle")
    err = VixDiskLib_Wait (h->handle);
  VDDK_CALL_END (VixDiskLib_Wait, 0);
  if (err != VIX_OK)
    VDDK_ERROR (err, "VixDiskLib_Wait");

  /* The documentation for Flush is missing, but the comment in the
   * header file seems to indicate that it waits for WriteAsync
   * commands to finish.  There's a new function Wait to wait for
   * those.  However I verified using strace that in fact Flush calls
   * fsync on the file so it appears to be the correct call to use
   * here.
   */
  VDDK_CALL_START (VixDiskLib_Flush, "handle")
    err = VixDiskLib_Flush (h->handle);
  VDDK_CALL_END (VixDiskLib_Flush, 0);
  if (err != VIX_OK) {
    VDDK_ERROR (err, "VixDiskLib_Flush");
    return -1;
  }

  return 0;
}

/* Try the QueryAllocatedBlocks call and if it's non-functional return
 * false.  At some point in future, perhaps when we move to baseline
 * VDDK >= 7, we can just assume it works and remove this test
 * entirely.
 */
static bool
test_can_extents (struct vddk_handle *h)
{
  VixError err;
  VixDiskLibBlockList *block_list;

  /* Suppress errors around this call.  See:
   * https://bugzilla.redhat.com/show_bug.cgi?id=1709211#c7
   */
  error_suppression = 1;

  VDDK_CALL_START (VixDiskLib_QueryAllocatedBlocks,
                   "handle, 0, %d sectors, %d sectors",
                   VIXDISKLIB_MIN_CHUNK_SIZE, VIXDISKLIB_MIN_CHUNK_SIZE)
    err = VixDiskLib_QueryAllocatedBlocks (h->handle,
                                           0, VIXDISKLIB_MIN_CHUNK_SIZE,
                                           VIXDISKLIB_MIN_CHUNK_SIZE,
                                           &block_list);
  VDDK_CALL_END (VixDiskLib_QueryAllocatedBlocks,
                 VIXDISKLIB_MIN_CHUNK_SIZE * VIXDISKLIB_SECTOR_SIZE);
  error_suppression = 0;
  if (err == VIX_OK) {
    VDDK_CALL_START (VixDiskLib_FreeBlockList, "block_list")
      VixDiskLib_FreeBlockList (block_list);
    VDDK_CALL_END (VixDiskLib_FreeBlockList, 0);
  }
  if (err != VIX_OK) {
    char *errmsg = VixDiskLib_GetErrorText (err, NULL);
    nbdkit_debug ("can_extents: "
                  "VixDiskLib_QueryAllocatedBlocks test failed, "
                  "extents support will be disabled: "
                  "original error: %s",
                  errmsg);
    VixDiskLib_FreeErrorText (errmsg);
    return 0;
  }

  return 1;
}

/* Add an extent to the list of extents. */
static int
add_extent (struct nbdkit_extents *extents,
            uint64_t *position, uint64_t next_position, bool is_hole)
{
  uint32_t type = 0;
  const uint64_t length = next_position - *position;

  if (is_hole) {
    type = NBDKIT_EXTENT_HOLE;
    /* Images opened as single link might be backed by another file in the
       chain, so the holes are not guaranteed to be zeroes. */
    if (!single_link)
      type |= NBDKIT_EXTENT_ZERO;
  }

  assert (*position <= next_position);
  if (*position == next_position)
    return 0;

  if (vddk_debug_extents)
    nbdkit_debug ("adding extent type %s at [%" PRIu64 "...%" PRIu64 "] "
                  "(length %" PRIu64 ")",
                  is_hole ? "hole" : "allocated data",
                  *position, next_position-1, length);
  if (nbdkit_add_extent (extents, *position, length, type) == -1)
    return -1;

  *position = next_position;
  return 0;
}

static int
get_extents_slow (struct command *cmd, struct vddk_handle *h)
{
  const uint32_t count = cmd->count;
  const uint64_t offset = cmd->offset;
  const bool req_one = cmd->req_one;
  struct nbdkit_extents *extents = cmd->ptr;
  uint64_t position, start_sector, size_sectors, last_queryable_sector, end;

  position = offset;

  /* We can only query whole chunks.  Therefore start with the
   * first chunk before offset.
   */
  start_sector =
    ROUND_DOWN (offset, VIXDISKLIB_MIN_CHUNK_SIZE * VIXDISKLIB_SECTOR_SIZE)
    / VIXDISKLIB_SECTOR_SIZE;

  /* Calculate the end byte + 1 that we're going to query, normally
   * this is offset + count.
   *
   * However since chunks are larger than sectors, for a disk which
   * has size which is not aligned to the chunk size there is a part
   * of the disk at the end that we can never query.  Reduce 'end' to
   * the maximum possible queryable part of the disk, and we'll deal
   * with the unaligned bit after the loop (RHEL-71694).
   */
  end = offset + count;
  size_sectors = h->size / VIXDISKLIB_SECTOR_SIZE;
  last_queryable_sector = ROUND_DOWN (size_sectors, VIXDISKLIB_MIN_CHUNK_SIZE);
  end = MIN (end, last_queryable_sector * VIXDISKLIB_SECTOR_SIZE);

  while (start_sector * VIXDISKLIB_SECTOR_SIZE < end) {
    VixError err;
    uint32_t i;
    uint64_t nr_chunks, nr_sectors;
    VixDiskLibBlockList *block_list;

    assert (IS_ALIGNED (start_sector, VIXDISKLIB_MIN_CHUNK_SIZE));

    nr_chunks =
      ROUND_UP (end - start_sector * VIXDISKLIB_SECTOR_SIZE,
                VIXDISKLIB_MIN_CHUNK_SIZE * VIXDISKLIB_SECTOR_SIZE)
      / (VIXDISKLIB_MIN_CHUNK_SIZE * VIXDISKLIB_SECTOR_SIZE);
    nr_chunks = MIN (nr_chunks, VIXDISKLIB_MAX_CHUNK_NUMBER);
    nr_sectors = nr_chunks * VIXDISKLIB_MIN_CHUNK_SIZE;

    VDDK_CALL_START (VixDiskLib_QueryAllocatedBlocks,
                     "handle, %" PRIu64 " sectors, %" PRIu64 " sectors, "
                     "%d sectors",
                     start_sector, nr_sectors, VIXDISKLIB_MIN_CHUNK_SIZE)
      err = VixDiskLib_QueryAllocatedBlocks (h->handle,
                                             start_sector, nr_sectors,
                                             VIXDISKLIB_MIN_CHUNK_SIZE,
                                             &block_list);
    VDDK_CALL_END (VixDiskLib_QueryAllocatedBlocks,
                   nr_sectors * VIXDISKLIB_SECTOR_SIZE);
    if (err != VIX_OK) {
      VDDK_ERROR (err, "VixDiskLib_QueryAllocatedBlocks");
      return -1;
    }

    for (i = 0; i < block_list->numBlocks; ++i) {
      uint64_t blk_offset, blk_length;

      blk_offset = block_list->blocks[i].offset * VIXDISKLIB_SECTOR_SIZE;
      blk_length = block_list->blocks[i].length * VIXDISKLIB_SECTOR_SIZE;
      nbdkit_debug ("QueryAllocatedBlocks returned allocated block at "
                    "%" PRIu64 "-%" PRIu64 " (length %" PRIu64 ")",
                    blk_offset, blk_offset + blk_length-1, blk_length);

      /* The query returns allocated blocks.  We must insert holes
       * between the blocks as necessary.
       */
      if ((position < blk_offset &&
           add_extent (extents, &position, blk_offset, true) == -1) ||
          (add_extent (extents,
                       &position, blk_offset + blk_length, false) == -1)) {
        VDDK_CALL_START (VixDiskLib_FreeBlockList, "block_list")
          VixDiskLib_FreeBlockList (block_list);
        VDDK_CALL_END (VixDiskLib_FreeBlockList, 0);
        return -1;
      }
    }
    VDDK_CALL_START (VixDiskLib_FreeBlockList, "block_list")
      VixDiskLib_FreeBlockList (block_list);
    VDDK_CALL_END (VixDiskLib_FreeBlockList, 0);

    /* There's an implicit hole after the returned list of blocks,
     * up to the end of the QueryAllocatedBlocks request.
     */
    if (add_extent (extents,
                    &position,
                    (start_sector + nr_sectors) * VIXDISKLIB_SECTOR_SIZE,
                    true) == -1) {
      return -1;
    }

    start_sector += nr_sectors;

    /* If one extent was requested, as long as we've added an extent
     * overlapping the original offset we're done.
     */
    if (req_one && position > offset)
      return 0;
  }

  /* If 'end' spanned beyond the last chunk of the disk, then we
   * reduced it above to avoid reading a chunk that extends beyond the
   * end of the underlying disk.  We have to synthesize an allocated
   * block here, which is what VDDK's example code does
   * (doc/samples/diskLib/vixDiskLibSample.cpp: DoGetAllocatedBlocks).
   */
  if (end < offset + count) {
    if (add_extent (extents, &position, offset + count, false) == -1)
      return -1;
  }

  return 0;
}

static int
pre_cache_extents (struct vddk_handle *h)
{
  struct nbdkit_extents *extents;
  uint64_t start_sector = 0;
  uint64_t nr_chunks_remaining =
    h->size / VIXDISKLIB_MIN_CHUNK_SIZE / VIXDISKLIB_SECTOR_SIZE;
  uint64_t position = 0;

  extents = nbdkit_extents_new (0, h->size);
  if (extents == NULL)
    return -1;

  /* Scan through the disk reading whole "chunks" (32 GB), the most
   * efficient way to use QueryAllocatedBlocks.
   */
  while (nr_chunks_remaining > 0) {
    VixError err;
    uint32_t i;
    uint64_t nr_chunks, nr_sectors;
    VixDiskLibBlockList *block_list;

    assert (IS_ALIGNED (start_sector, VIXDISKLIB_MIN_CHUNK_SIZE));

    nr_chunks = MIN (nr_chunks_remaining, VIXDISKLIB_MAX_CHUNK_NUMBER);
    nr_sectors = nr_chunks * VIXDISKLIB_MIN_CHUNK_SIZE;

    VDDK_CALL_START (VixDiskLib_QueryAllocatedBlocks,
                     "handle, %" PRIu64 " sectors, %" PRIu64 " sectors, "
                     "%d sectors",
                     start_sector, nr_sectors, VIXDISKLIB_MIN_CHUNK_SIZE)
      err = VixDiskLib_QueryAllocatedBlocks (h->handle,
                                             start_sector, nr_sectors,
                                             VIXDISKLIB_MIN_CHUNK_SIZE,
                                             &block_list);
    VDDK_CALL_END (VixDiskLib_QueryAllocatedBlocks,
                   nr_sectors * VIXDISKLIB_SECTOR_SIZE);
    if (err != VIX_OK) {
      VDDK_ERROR (err, "VixDiskLib_QueryAllocatedBlocks");
      nbdkit_extents_free (extents);
      return -1;
    }

    for (i = 0; i < block_list->numBlocks; ++i) {
      uint64_t blk_offset, blk_length;

      blk_offset = block_list->blocks[i].offset * VIXDISKLIB_SECTOR_SIZE;
      blk_length = block_list->blocks[i].length * VIXDISKLIB_SECTOR_SIZE;
      nbdkit_debug ("QueryAllocatedBlocks returned allocated block at "
                    "%" PRIu64 "-%" PRIu64 " (length %" PRIu64 ")",
                    blk_offset, blk_offset + blk_length-1, blk_length);

      /* The query returns allocated blocks.  We must insert holes
       * between the blocks as necessary.
       */
      if ((position < blk_offset &&
           add_extent (extents, &position, blk_offset, true) == -1) ||
          (add_extent (extents,
                       &position, blk_offset + blk_length, false) == -1)) {
        VDDK_CALL_START (VixDiskLib_FreeBlockList, "block_list")
          VixDiskLib_FreeBlockList (block_list);
        VDDK_CALL_END (VixDiskLib_FreeBlockList, 0);
        nbdkit_extents_free (extents);
        return -1;
      }
    }
    VDDK_CALL_START (VixDiskLib_FreeBlockList, "block_list")
      VixDiskLib_FreeBlockList (block_list);
    VDDK_CALL_END (VixDiskLib_FreeBlockList, 0);

    /* There's an implicit hole after the returned list of blocks,
     * up to the end of the QueryAllocatedBlocks request.
     */
    if (add_extent (extents,
                    &position,
                    (start_sector + nr_sectors) * VIXDISKLIB_SECTOR_SIZE,
                    true) == -1) {
      nbdkit_extents_free (extents);
      return -1;
    }

    start_sector += nr_sectors;
    nr_chunks_remaining -= nr_chunks;
  }

  /* Add the allocated unaligned bit at the end. */
  if (position < h->size) {
    if (add_extent (extents, &position, h->size, false) == -1) {
      nbdkit_extents_free (extents);
      return -1;
    }
  }

  /* Save the pre-cached extents in the handle. */
  h->extents = extents;
  return 0;
}

static int
get_extents_from_cache (struct command *cmd, struct vddk_handle *h)
{
  struct nbdkit_extents *rextents = cmd->ptr;
  struct nbdkit_extent e;
  size_t i;

  /* We can just copy from the pre-cached extents in the handle which
   * cover the entire disk, into the returned extents, because
   * nbdkit_add_extent does the right thing.
   */
  for (i = 0; i < nbdkit_extents_count (h->extents); ++i) {
    e = nbdkit_get_extent (h->extents, i);
    if (nbdkit_add_extent (rextents, e.offset, e.length, e.type) == -1)
      return -1;
  }

  return 0;
}

/* Handle extents.
 *
 * Oh QueryAllocatedBlocks, how much I hate you.  The API has two
 * enormous problems: (a) It's slow, taking about 1 second per
 * invocation regardless of how much or little data you request.  (b)
 * It serialises all other requests to the disk, like concurrent
 * reads.
 *
 * NBD / nbdkit doesn't help much either by having a 4GB - 1 byte
 * limit on the size of extent requests.  This means that for each 4GB
 * of disk, we will need to run QueryAllocatedBlocks twice.  For a 1TB
 * virtual disk, about 500 seconds would be used directly in the API
 * calls, and much more time is lost because of serialization.
 *
 * To work around these problems, in the readonly case (used by
 * virt-v2v), when the first NBD_BLOCK_STATUS request is received, we
 * will read over the whole disk and cache the extents.  We will read
 * in 32 GB chunks (the maximum possible for the underlying
 * QueryAllocatedBlocks API).  For a 1TB disk this will take ~ 30
 * seconds, but avoids all the overheads above.  The cached extents
 * are stored in the handle, and subsequent NBD_BLOCK_STATUS will use
 * the cache only.
 *
 * For writable disks we can't easily do any caching so don't attempt
 * it.
 */
static int
do_extents (struct command *cmd, struct vddk_handle *h)
{
  if (h->readonly && !h->extents) {
    time_t start_t, end_t;

    time (&start_t);
    nbdkit_debug ("vddk: pre-caching extents");

    if (pre_cache_extents (h) == -1)
      return -1;

    time (&end_t);
    nbdkit_debug ("vddk: finished pre-caching extents in %d second(s)",
                  (int) (end_t - start_t));
  }

  if (h->extents)
    return get_extents_from_cache (cmd, h);
  else
    return get_extents_slow (cmd, h);
}

/* Background worker thread, one per connection, which is where the
 * VDDK commands are issued.
 */
void *
vddk_worker_thread (void *handle)
{
  struct vddk_handle *h = handle;
  bool stop = false;
  bool can_extents;

  /* Test if QueryAllocatedBlocks will work. */
  can_extents = test_can_extents (h);

  while (!stop) {
    struct command *cmd;
    int r;
    bool async = false;

    /* Wait until we are sent at least one command. */
    {
      ACQUIRE_LOCK_FOR_CURRENT_SCOPE (&h->commands_lock);
      while (h->commands.len == 0)
        pthread_cond_wait (&h->commands_cond, &h->commands_lock);
      cmd = h->commands.ptr[0];
      command_queue_remove (&h->commands, 0);
    }

    switch (cmd->type) {
    case STOP:
      r = do_stop (cmd, h);
      stop = true;
      break;

    case INFO:
      r = do_info (cmd, h);
      break;

    case READ:
      r = do_read (cmd, h);
      /* If async is true, don't retire this command now. */
      async = r == 0;
      break;

    case WRITE:
      r = do_write (cmd, h);
      /* If async is true, don't retire this command now. */
      async = r == 0;
      break;

    case FLUSH:
      r = do_flush (cmd, h);
      break;

    case CAN_EXTENTS:
      *(int *)cmd->ptr = can_extents;
      r = 0;
      break;

    case EXTENTS:
      /* If we returned false above, we should never be called here. */
      assert (can_extents);
      r = do_extents (cmd, h);
      break;

    default: abort (); /* impossible, but keeps GCC happy */
    } /* switch */

    if (!async) {
      /* Update the command status. */
      ACQUIRE_LOCK_FOR_CURRENT_SCOPE (&cmd->mutex);
      cmd->status = r >= 0 ? SUCCEEDED : FAILED;

      /* For synchronous commands signal the caller thread that the
       * command has completed.  (Asynchronous commands are completed in
       * the callback handler).
       */
      pthread_cond_signal (&cmd->cond);
    }
  } /* while (!stop) */

  /* Exit the worker thread. */
  return NULL;
}
