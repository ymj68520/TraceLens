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
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <assert.h>

#define NBDKIT_API_VERSION 2
#include <nbdkit-plugin.h>

#include <nfsc/libnfs.h>
#include <nfsc/libnfs-raw.h>     /* rpc_set_debug, rpc_set_log_cb */

#include "ispowerof2.h"
#include "sysconf.h"

/* Do we have the optional multithreading feature of libnfs?  This is
 * a libnfs configure-time feature, and not all Linux distros enable
 * it.
 */
#ifdef HAVE_NFS_MT_SERVICE_THREAD_START
#define MULTITHREADING 1
#endif

static const char *uri;          /* uri parameter */
static bool readonly_cli;        /* readonly parameter */

static struct nfs_context *nfsc; /* libnfs context */
static struct nfs_url *nfsu;     /* libnfs parsed URL */
static struct nfsfh *nfsfh;      /* libnfs opened file handle */

static bool mounted;             /* flag to indicate we are mounted */

#if MULTITHREADING
static bool multithreading;      /* flag to indicate we enabled MT */
#endif

static void
nfs_plugin_unload (void)
{
  if (nfsfh)
    nfs_close (nfsc, nfsfh);
#if MULTITHREADING
  if (multithreading)
    nfs_mt_service_thread_stop (nfsc);
#endif
  if (mounted)
    nfs_umount (nfsc);
  if (nfsu)
    nfs_destroy_url (nfsu);
  if (nfsc)
    nfs_destroy_context (nfsc);
}

static void
nfs_plugin_dump_plugin (void)
{
#if MULTITHREADING
  printf ("libnfs_multithreading=yes\n");
#endif
}

static int
nfs_plugin_config (const char *key, const char *value)
{
  int r;

  if (strcmp (key, "uri") == 0) {
    uri = value;
  }
  else if (strcmp (key, "readonly") == 0) {
    r = nbdkit_parse_bool (value);
    if (r == -1)
      return -1;
    readonly_cli = r;
  }
  else {
    nbdkit_error ("unknown parameter '%s'", key);
    return -1;
  }

  return 0;
}

static int
nfs_plugin_config_complete (void)
{
  if (uri == NULL) {
    nbdkit_error ("'uri' parameter is missing");
    return -1;
  }

  return 0;
}

#define nfs_plugin_config_help \
  "uri=nfs://...       (required) The RFC 2224 NFS URI.\n" \
  "readonly=true|false            If set, mount file read-only." \

static int
open_file (void)
{
  int err;
  int flags;

  assert (nfsfh == NULL);

  flags = readonly_cli ? O_RDONLY : O_RDWR;
  err = nfs_open (nfsc, nfsu->file, flags, &nfsfh);
  if (err < 0) {
    errno = -err;
    nbdkit_error ("nfs_open: %s: %m", nfsu->file);
    return -1;
  }
  return 0;
}

/* -D nfs.debug=<N> */
NBDKIT_DLL_PUBLIC int nfs_debug_debug = 0;

static void
log_callback (struct rpc_context *rpc, int level, char *message, void *vp)
{
  nbdkit_debug ("%s", message);
}

static int
nfs_plugin_get_ready (void)
{
  int err;
  struct rpc_context *rpc;

  nfsc = nfs_init_context ();
  if (nfsc == NULL) {
    nbdkit_error ("could not create nfs context");
    return -1;
  }

  rpc = nfs_get_rpc_context (nfsc);
  if (rpc) {
    /* Set the debug level through the nbdkit debug flag. */
    if (nfs_debug_debug > 0)
      rpc_set_debug (rpc, nfs_debug_debug);

    /* Ensure libnfs logging messages are sent to nbdkit's log facility. */
    rpc_set_log_cb (rpc, log_callback, NULL);
  }

#ifdef HAVE_NFS_SET_READONLY
  /* Force readonly if the readonly=true flag was given.  This
   * shouldn't be necessary for nbdkit, but provides extra safety as
   * libnfs will error out if we somehow call any write functions.
   */
  if (readonly_cli)
    nfs_set_readonly (nfsc, 1);
#endif

  /* Parse the URI. */
  nfsu = nfs_parse_url_full (nfsc, uri);
  if (nfsu == NULL) {
    nbdkit_error ("could not parse the NFS URI: %s", uri);
    return -1;
  }
  /* I think these are internal errors that should never happen. */
  if (nfsu->server == NULL) {
    nbdkit_error ("nfsu->server was parsed as NULL");
    return -1;
  }
  nbdkit_debug ("nfs: nfsu->server = %s", nfsu->server);
  if (nfsu->path == NULL) {
    nbdkit_error ("nfsu->path was parsed as NULL");
    return -1;
  }
  nbdkit_debug ("nfs: nfsu->path = %s", nfsu->path);
  if (nfsu->file == NULL) {
    nbdkit_error ("nfsu->file was parsed as NULL");
    return -1;
  }
  nbdkit_debug ("nfs: nfsu->file = %s", nfsu->file);

  /* There must be a separate file element. */
  if (strcmp (nfsu->file, "") == 0 || strcmp (nfsu->file, "/") == 0) {
    nbdkit_error ("NFS URI did not contain a filename: %s", uri);
    return -1;
  }

  /* Mount the NFS mountpoint. */
  err = nfs_mount (nfsc, nfsu->server, nfsu->path);
  if (err < 0) {
#ifndef WIN32
    const bool running_as_root = geteuid () == 0;
#else
    const bool running_as_root = true;
#endif

    errno = -err;
    if (!running_as_root && errno == EPERM) {
      nbdkit_error ("could not mount %s (server=%s, path=%s): "
                    "some NFS servers might require nbdkit to run as root: "
                    "original error: %m",
                    uri, nfsu->server, nfsu->path);
    }
    else {
      nbdkit_error ("could not mount %s (server=%s, path=%s): %m",
                    uri, nfsu->server, nfsu->path);
    }
    return -1;
  }
  mounted = true;

  /* When we don't have multi-threading we can open the file now and
   * if that fails, print an error before we fork.  With
   * multi-threading we have to open the file after starting up the
   * background threads after forking, see nfs_plugin_after_fork.
   */
#if !MULTITHREADING
  if (open_file () == -1)
    return -1;
#endif

  return 0;
}

#if MULTITHREADING
static int
nfs_plugin_after_fork (void)
{
  int err;

  err = nfs_mt_service_thread_start (nfsc);
  if (err < 0) {
    errno = -err;
    nbdkit_error ("could not enable multithreading support: %m");
    return -1;
  }
  multithreading = true;

  if (open_file () == -1)
    return -1;

  return 0;
}
#endif

#if MULTITHREADING
#define THREAD_MODEL NBDKIT_THREAD_MODEL_PARALLEL
#else
#define THREAD_MODEL NBDKIT_THREAD_MODEL_SERIALIZE_ALL_REQUESTS
#endif

struct handle {
  int readonly;
};

static void *
nfs_plugin_open (int readonly)
{
  struct handle *h;

  h = calloc (1, sizeof *h);
  if (h == NULL) {
    nbdkit_error ("calloc: %m");
    return NULL;
  }
  h->readonly = readonly;
  return h;
}

static int
nfs_plugin_can_write (void *handle)
{
  struct handle *h = handle;

  /* Force readonly if either nbdkit -r or readonly=true */
  if (h->readonly || readonly_cli)
    return 0;
  return 1;
}

/* Multi-conn is safe, see:
 * https://groups.google.com/g/libnfs/c/Mq0Ialk2k2o
 */
static int
nfs_plugin_can_multi_conn (void *handle)
{
  return 1;
}

static int
nfs_plugin_block_size (void *handle,
                       uint32_t *minimum,
                       uint32_t *preferred,
                       uint32_t *maximum)
{
  *minimum = 1;
  /* NFS reads and writes go through the page cache, so return the
   * machine page size here.
   */
  *preferred = sysconf (_SC_PAGESIZE);
  assert (*preferred > 1);
  assert (is_power_of_2 (*preferred));
  *maximum = 0xffffffff;
  return 0;
}

/* Get the file size. */
static int64_t
nfs_plugin_get_size (void *handle)
{
  int err;
  struct nfs_stat_64 statbuf;

  err = nfs_fstat64 (nfsc, nfsfh, &statbuf);
  if (err < 0) {
    errno = -err;
    nbdkit_error ("nfs_fstat64: %s: %m", nfsu->file);
    return -1;
  }

  /* XXX Does this work for remote devices? */
  return statbuf.nfs_size;
}

/* Read data from the file. */
static int
nfs_plugin_pread (void *handle, void *buf,
                  uint32_t count, uint64_t offset,
                  uint32_t flags)
{
  ssize_t r;

  while (count > 0) {
    r = nfs_pread (nfsc, nfsfh, buf, count, offset);
    if (r < 0) {
      errno = -r;
      nbdkit_error ("nfs_pread: %s: %m", nfsu->file);
    }
    if (r == 0) {
      errno = EINVAL;
      nbdkit_error ("nfs_pread: unexpected end of file");
      return -1;
    }
    buf += r;
    count -= r;
    offset += r;
  }

  return 0;
}

static int nfs_plugin_flush (void *handle, uint32_t flags);

/* Write data to the file. */
static int
nfs_plugin_pwrite (void *handle, const void *buf,
                   uint32_t count, uint64_t offset,
                   uint32_t flags)
{
  while (count > 0) {
    ssize_t r = nfs_pwrite (nfsc, nfsfh, buf, count, offset);
    if (r < -1) {
      errno = -r;
      nbdkit_error ("nfs_pwrite: %s: %m", nfsu->file);
      return -1;
    }
    buf += r;
    count -= r;
    offset += r;
  }

  if ((flags & NBDKIT_FLAG_FUA) && nfs_plugin_flush (handle, 0) == -1)
    return -1;

  return 0;
}

/* Flush writes. */
static int
nfs_plugin_flush (void *handle, uint32_t flags)
{
  int err;

  err = nfs_fsync (nfsc, nfsfh);
  if (err < 0) {
    errno = -err;
    nbdkit_error ("nfs_fsync: %s: %m", nfsu->file);
    return -1;
  }
  return 0;
}

static struct nbdkit_plugin plugin = {
  .name              = "nfs",
  .longname          = "nbdkit nfs plugin",
  .version           = PACKAGE_VERSION,
  .unload            = nfs_plugin_unload,
  .dump_plugin       = nfs_plugin_dump_plugin,
  .config            = nfs_plugin_config,
  .config_complete   = nfs_plugin_config_complete,
  .config_help       = nfs_plugin_config_help,
  .magic_config_key  = "uri",
  .get_ready         = nfs_plugin_get_ready,
#if MULTITHREADING
  .after_fork        = nfs_plugin_after_fork,
#endif
  .open              = nfs_plugin_open,
  .get_size          = nfs_plugin_get_size,
  .can_write         = nfs_plugin_can_write,
  .can_multi_conn    = nfs_plugin_can_multi_conn,
  .block_size        = nfs_plugin_block_size,
  .pread             = nfs_plugin_pread,
  .pwrite            = nfs_plugin_pwrite,
  .flush             = nfs_plugin_flush,
  .errno_is_preserved = 1,
};

NBDKIT_REGISTER_PLUGIN (plugin)
