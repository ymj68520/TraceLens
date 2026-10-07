/* NBD client library in userspace
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

/* Check for a requirement or skip the test. */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>

#include "requires.h"

void
requires (const char *cmd)
{
  printf ("requires %s\n", cmd);
  fflush (stdout);
  if (system (cmd) != 0) {
    printf ("Test skipped because prerequisite is missing or not working.\n");
    exit (77);
  }
}

void
requires_not (const char *cmd)
{
  printf ("requires_not %s\n", cmd);
  fflush (stdout);
  if (system (cmd) == 0) {
    printf ("Test skipped because prerequisite is missing or not working.\n");
    exit (77);
  }
}

void
requires_not_exists (const char *filename)
{
  printf ("requires_not_exists %s\n", filename);
  fflush (stdout);
  if (access (filename, F_OK) == 0) {
    printf ("Test skipped because file '%s' exists.\n", filename);
    exit (77);
  }
}

#ifdef QEMU_NBD
/* Check qemu-nbd was compiled with support for TLS. */
void
requires_qemu_nbd_tls_support (void)
{
  char cmd[256];

  /* Note the qemu-nbd command will fail in some way.  We're only
   * interested in the error message that it prints.
   */
  snprintf (cmd, sizeof cmd,
            "! " QEMU_NBD " --object tls-creds-x509,id=tls0 2>&1 \\\n"
            "  | grep -sq 'TLS credentials support requires GNUTLS'\n");
  requires (cmd);
}

/* Check qemu-nbd supports PSK (version 3.0.0 and above). */
void
requires_qemu_nbd_tls_psk_support (void)
{
  char cmd[256];

  /* Note the qemu-nbd command will fail in some way.  We're only
   * interested in the error message that it prints.
   */
  snprintf (cmd, sizeof cmd,
            "! " QEMU_NBD " --object tls-creds-psk,id=tls0 / 2>&1 \\\n"
            "  | grep -sq 'invalid object type'\n");
  requires (cmd);
}
#else /* !QEMU_NBD */
void
requires_qemu_nbd_tls_support (void)
{
  fprintf (stderr, "qemu-nbd not available at compile time\n");
  exit (77);
}

void
requires_qemu_nbd_tls_psk_support (void)
{
  fprintf (stderr, "qemu-nbd not available at compile time\n");
  exit (77);
}
#endif

#ifdef NBD_SERVER
/* On some distros, nbd-server is built without support for syslog
 * which prevents use of inetd mode.  Instead nbd-server will exit with
 * this error:
 *
 *   Error: inetd mode requires syslog
 *   Exiting.
 *
 * https://listman.redhat.com/archives/libguestfs/2022-January/msg00003.html
 */
void
requires_nbd_server_supports_inetd (void)
{
  char cmd[256];

  snprintf (cmd, sizeof cmd, "\"%s\" --version", NBD_SERVER);
  requires (cmd);
  snprintf (cmd, sizeof cmd,
            "grep 'inetd mode requires syslog' \"$(command -v \"%s\")\"",
            NBD_SERVER);
  requires_not (cmd);
}
#else /* !NBD_SERVER */
void
requires_nbd_server_supports_inetd (void)
{
  fprintf (stderr, "nbd-server not available at compile time\n");
  exit (77);
}
#endif

/* If SERVER_PARAMS contains --tls-verify-peer we must make sure
 * that nbdkit supports that option.
 */
void
requires_nbdkit_tls_verify_peer (void)
{
#ifdef NBDKIT
  requires (NBDKIT " --tls-verify-peer -U - null --run 'exit 0'");
#else
  fprintf (stderr, "nbdkit not available at compile time\n");
  exit (77);
#endif
}

/* Check that ssh to localhost will work without any passwords or phrases.
 * See nbdkit:tests/test-ssh.sh
 */
void
requires_ssh_localhost (void)
{
  requires ("ssh -V");
  requires ("ssh -o PreferredAuthentications=none,publickey "
            "-o StrictHostKeyChecking=no localhost echo </dev/null");
}
