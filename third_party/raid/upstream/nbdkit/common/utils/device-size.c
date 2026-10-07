/* nbdkit
 * Copyright Red Hat
 *
 * This is based on code from util-linux/lib/blkdev.c which is
 * distributed under a compatible license.
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

#ifndef WIN32

#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <errno.h>
#include <assert.h>

#ifdef HAVE_SYS_IOCTL_H
#include <sys/ioctl.h>
#endif

#ifdef HAVE_SYS_DISK_H
#include <sys/disk.h>           /* for Darwin and FreeBSD */
#endif

#ifdef HAVE_SYS_DISKLABEL_H
#include <sys/disklabel.h>      /* for FreeBSD */
#endif

#ifdef HAVE_LINUX_FS_H
#include <linux/fs.h>           /* for BLKGETSIZE{64,} on Linux */
#endif

#include "utils.h"

static int64_t find_size_by_seeking (int fd);
static long valid_offset (int fd, int64_t offset);

/* Calculate the size of file or block device 'fd'.
 *
 * If 'statbuf' is non-NULL, it should contain the result of a
 * previous call to fstat(2).  Otherwise, this function may need to
 * call fstat.  It may need to seek on the file descriptor or use
 * ioctl.
 *
 * NB: In general this function requires O_RDONLY/O_RDWR access to
 * block devices, because otherwise the find_size_by_seeking method
 * doesn't work.
 *
 * On error, sets errno and returns -1.
 */
int64_t
device_size (int fd, const struct stat *statbuf_from_caller)
{
  const struct stat *sb;
  struct stat statbuf;
#if defined(DKIOCGETBLOCKCOUNT) || defined(BLKGETSIZE64)
  uint64_t u64;
#endif

  if (statbuf_from_caller != NULL)
    sb = statbuf_from_caller;
  else {
    if (fstat (fd, &statbuf) == -1)
      return -1;
    sb = &statbuf;
  }

  /* Assume st_size works for regular files. */
  if (S_ISREG (sb->st_mode))
    return sb->st_size;
  /* Error for anything else which is not a block device. */
  else if (!S_ISBLK (sb->st_mode)) {
    errno = ENOTBLK;
    return -1;
  }

  /* Apple Darwin */
#ifdef DKIOCGETBLOCKCOUNT
  if (ioctl (fd, DKIOCGETBLOCKCOUNT, &u64) >= 0) {
    u64 <<= 9;
    return u64;
  }
#endif

  /* Linux */
#ifdef BLKGETSIZE64
  if (ioctl (fd, BLKGETSIZE64, &u64) >= 0)
    return u64;
#endif

#ifdef BLKGETSIZE
  unsigned long ul;
  if (ioctl (fd, BLKGETSIZE, &ul) >= 0)
    return (uint64_t)ul << 9;
#endif

  /* FreeBSD */
#ifdef DIOCGMEDIASIZE
  off_t off;
  if (ioctl (fd, DIOCGMEDIASIZE, &off) >= 0)
    return off;
#endif

  /* Fall back to seeking. */
  return find_size_by_seeking (fd);
}

/* The two functions below were copied from util-linux and it's not
 * obvious what it does or how it works, so ...
 *
 * The aim of this function is to be a fallback to find the size of a
 * block device by seeking to the end.  We used to use lseek(SEEK_END)
 * for this, but that isn't portable to some BSDs.
 *
 * It starts by setting [low, high] to [0, 1024] and checking if the
 * high offset (1024) is valid, where "valid" means is seekable and
 * you can read a byte from that offset.  If valid, it tries again
 * with [1024, 2048], [2048, 4096], doubling each time.
 *
 * When the high offset is no longer valid, we enter the second loop
 * with a [low, high] range where we know the end of the disk must be
 * >= low and < high.  The second loop does a binary search to find
 * the end of the disk.
 */
static int64_t
find_size_by_seeking (int fd)
{
  int64_t high, low = 0;

  /* Find range. */
  for (high = 1024; valid_offset (fd, high); ) {
    if (high == INT64_MAX) {
      errno = EFBIG;
      return -1;
    }

    low = high;

    if (high >= INT64_MAX/2)
      high = INT64_MAX;
    else
      high *= 2;
  }

  /* Binary search in >= low, < high. */
  while (low < high - 1) {
    int64_t mid = (low + high) / 2;

    if (valid_offset (fd, mid))
      low = mid;
    else
      high = mid;
  }

  /* This is in the original code, but what is it for?  I initially
   * thought it was meant to reset the seek offset to 0, but it
   * actually sets it to 1.  Is that a mistake?  Or does it do
   * something else?  XXX
   */
  valid_offset (fd, 0);

  /* Return the size, which is last offset + 1. */
  return low + 1;
}

static long
valid_offset (int fd, int64_t offset)
{
  char ch;
  ssize_t r;

  if (lseek (fd, offset, SEEK_SET) < 0)
    return 0;
  /* The original code in util-linux just checks for < 1, but that's
   * wrong.  If the file descriptor is not open for reading
   * (ie. O_WRONLY) then this fails with EBADF, resulting in
   * calculating an apparent size of 1.  Assert fail if we see EBADF
   * here as it's a programming error.
   */
  r = read (fd, &ch, 1);
  assert (r != -1 || errno != EBADF);
  if (r < 1) return 0;
  return 1;
}

#endif /* !WIN32 */
