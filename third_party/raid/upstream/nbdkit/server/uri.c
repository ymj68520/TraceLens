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

#include "open_memstream.h"
#include "utils.h"

#include "internal.h"

char *uri;                      /* NBD URI */

char *
make_uri (void)
{
  FILE *fp;
  size_t len = 0;
  char *r = NULL;
  const bool tls_required = tls == 2;
  const char *scheme;
  bool query_appended;

  switch (service_mode) {
  case SERVICE_MODE_SOCKET_ACTIVATION:
  case SERVICE_MODE_LISTEN_STDIN:
    /* can't form a URI, uri will be NULL */
    goto out;
  default: ;
  }

  /* Work out the scheme. */
  switch (service_mode) {
  case SERVICE_MODE_TCPIP:
    scheme = tls_required ? "nbds" : "nbd";
    break;
  case SERVICE_MODE_UNIXSOCKET:
    scheme = tls_required ? "nbds+unix" : "nbd+unix";
    break;
  case SERVICE_MODE_VSOCK:
    scheme = tls_required ? "nbds+vsock" : "nbd+vsock";
    break;
  case SERVICE_MODE_SOCKET_ACTIVATION:
  case SERVICE_MODE_LISTEN_STDIN:
    /* these labels are not-reachable, see above */
    /*FALLTHROUGH*/
  default:
    abort ();
  }

  /* Open the memory stream to store the URI. */
  fp = open_memstream (&r, &len);
  if (fp == NULL) {
    perror ("uri: open_memstream");
    exit (EXIT_FAILURE);
  }

  fprintf (fp, "%s://", scheme);

  switch (service_mode) {
  case SERVICE_MODE_UNIXSOCKET:
    if (export_name && strcmp (export_name, "") != 0) {
      putc ('/', fp);
      uri_quote (export_name, fp);
    }
    fprintf (fp, "?socket=");
    uri_quote (unixsocket, fp);
    query_appended = true;
    break;
  case SERVICE_MODE_VSOCK:
    /* 1 = VMADDR_CID_LOCAL */
    putc ('1', fp);
    if (port) {
      putc (':', fp);
      fputs (port, fp);
    }
    if (export_name && strcmp (export_name, "") != 0) {
      putc ('/', fp);
      uri_quote (export_name, fp);
    }
    query_appended = false;
    break;
  case SERVICE_MODE_TCPIP:
    fputs ("localhost", fp);
    if (port) {
      putc (':', fp);
      fputs (port, fp);
    }
    if (export_name && strcmp (export_name, "") != 0) {
      putc ('/', fp);
      uri_quote (export_name, fp);
    }
    query_appended = false;
    break;

  case SERVICE_MODE_SOCKET_ACTIVATION:
  case SERVICE_MODE_LISTEN_STDIN:
    /* these labels are not-reachable, see above */
    /*FALLTHROUGH*/
  default:
    abort ();
  }

  /* For TLS, append tls-certificates or tls-psk-file.  Note that
   * tls-certificates requires libnbd >= 1.10 (Sep 2021) and it fails
   * strangely with older versions (RHEL 8 is too old).  Hopefully
   * this will resolve itself over time as people upgrade libnbd.
   * Qemu ignores these parameters, see:
   * https://lists.libguestfs.org/archives/list/guestfs@lists.libguestfs.org/message/PDXCGDWJD2FHFNQNSFKH752IMVOAW2KI/
   */
  if (tls_required && (tls_certificates_dir || tls_psk)) {
    putc (query_appended ? '&' : '?', fp);
    if (tls_certificates_dir) {
      fputs ("tls-certificates=", fp);
      uri_quote (tls_certificates_dir, fp);
    }
    else if (tls_psk) {
      fputs ("tls-psk-file=", fp);
      uri_quote (tls_psk, fp);
    }
  }

  if (close_memstream (fp) == EOF) {
    perror ("uri: close_memstream");
    exit (EXIT_FAILURE);
  }

 out:
  if (r)
    debug ("NBD URI: %s", r);
  else
    debug ("no NBD URI because service mode is %s",
           service_mode_string (service_mode));

  return r;
}
