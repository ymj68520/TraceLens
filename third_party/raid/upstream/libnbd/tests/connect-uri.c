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

/* Test connecting over an NBD URI. */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <ctype.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>

#include <libnbd.h>

#include "pick-a-port.h"
#include "requires.h"

#ifdef DEFINE_STR_AS_UNIX_SOCKET
static char str[] = "/tmp/nbdXXXXXX";

static void
unlink_unix_socket (void)
{
  unlink (str);
}
#endif

#ifdef DEFINE_STR_AS_PORT
static char str[] = "12345";
#endif

#ifndef SKIP_GET_URI
static int compare_uris (const char *uri1, const char *uri2);
#endif

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  const char *s;
  char *pidfile;
  pid_t pid;
  size_t i;
#ifndef SKIP_GET_URI
  char *get_uri;
#endif
  char *uri;

  /* Check requirements or skip the test. */
#ifdef REQUIRES
  REQUIRES
#endif

#ifdef DEFINE_STR_AS_UNIX_SOCKET
  int fd = mkstemp (str);
  if (fd == -1 ||
      close (fd) == -1) {
    perror (str);
    exit (EXIT_FAILURE);
  }
  /* We have to remove the temporary file first, since we will create
   * a socket in its place, and ensure the socket is removed on exit.
   */
  unlink_unix_socket ();
  atexit (unlink_unix_socket);
#endif

#ifdef DEFINE_STR_AS_PORT
  int port = pick_a_port ();
  snprintf (str, sizeof str, "%d", port);
#endif

  if (asprintf (&uri, URI) == -1) {
    perror ("asprintf");
    exit (EXIT_FAILURE);
  }

  /* Generate a PID file (for nbdkit -P) derived from the basename of
   * the current binary, which is unique for each test.
   */
  s = strrchr (argv[0], '/');
  if (s) s++; else s = argv[0];
  if (asprintf (&pidfile, "%s.pid", s) == -1) {
    perror ("asprintf");
    exit (EXIT_FAILURE);
  }
  if (strstr (pidfile, "connect") == NULL)
    abort ();

  unlink (pidfile);

  pid = fork ();
  if (pid == -1) {
    perror ("fork");
    exit (EXIT_FAILURE);
  }
  if (pid == 0) {
    execlp (NBDKIT,
            "nbdkit", "-f", "-v", "--exit-with-parent",
//          "-D", "nbdkit.tls.log=99",
            "-P", pidfile,
            SERVER_PARAMS,
            "null", NULL);
    perror ("nbdkit");
    _exit (EXIT_FAILURE);
  }

  /* Wait for nbdkit to start listening. */
  for (i = 0; i < 60; ++i) {
    if (access (pidfile, F_OK) == 0)
      break;
    sleep (1);
  }
  unlink (pidfile);
  free (pidfile);

  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (nbd_supports_uri (nbd) != 1) {
    fprintf (stderr, "skip: compiled without URI support\n");
    exit (77);
  }
  if (! nbd_is_uri (nbd, uri)) {
    fprintf (stderr, "%s: nbd_is_uri returned false for this URI: %s\n",
             argv[0], uri);
    exit (EXIT_FAILURE);
  }

  nbd_set_uri_allow_tls_priority (nbd, true);
  nbd_set_uri_allow_local_file (nbd, true);
  if (nbd_connect_uri (nbd, uri) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Check we negotiated the right kind of connection. */
  if (strncmp (uri, "nbds", 4) == 0) {
    if (! nbd_get_tls_negotiated (nbd)) {
      fprintf (stderr, "%s: failed to negotiate a TLS connection\n",
               argv[0]);
      exit (EXIT_FAILURE);
    }
  }

#ifndef SKIP_GET_URI
  /* Usually the URI returned by nbd_get_uri should be the same as the
   * one passed to nbd_connect_uri, or at least it will be in our test
   * cases.
   */
  get_uri = nbd_get_uri (nbd);
  if (get_uri == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  if (compare_uris (uri, get_uri) != 0) {
    fprintf (stderr, "%s: connect URI %s != get URI %s\n",
             argv[0], uri, get_uri);
    exit (EXIT_FAILURE);
  }
  free (get_uri);
#endif

  if (nbd_shutdown (nbd, 0) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  nbd_close (nbd);
  free (uri);
  exit (EXIT_SUCCESS);
}

#ifdef HAVE_STRCASESTR
#define case_insensitive_substring(s1, s2) (strcasestr ((s1), (s2)) != NULL)
#else
static int
case_insensitive_substring (const char *haystack, const char *needle)
{
  /* strcasestr was implemented first in GNU libc, and later added to
   * FreeBSD and OpenBSD.  However it is not in POSIX so far.
   *
   * Don't use this as a general replacement for strcasestr.  It's not
   * unicode safe, nor efficient, so only suitable for this test.
   */
  char *s1 = strdup (haystack);
  char *s2 = strdup (needle);
  size_t i, n;
  int r;

  if (!s1 || !s2) abort ();

  n = strlen (s1);
  for (i = 0; i < n; ++i)
    s1[i] = tolower (s1[i]);
  n = strlen (s2);
  for (i = 0; i < n; ++i)
    s2[i] = tolower (s2[i]);
  r = strstr (s1, s2) != NULL;

  free (s1);
  free (s2);
  return r;
}
#endif

#ifndef SKIP_GET_URI
/* Naive comparison of two URIs, enough to get the tests to pass but
 * it does not take into account things like quoting.  The difference
 * between the URI we set and the one we read back is the order of
 * query fields.
 */
static int
compare_uris (const char *uri1, const char *uri2)
{
  size_t n;
  int r;

  /* Compare the parts before the query fields. */
  n = strcspn (uri1, "?");
  r = strncasecmp (uri1, uri2, n);
  if (r != 0) return r;

  if (strlen (uri1) == n)
    return 0;
  uri1 += n + 1;
  uri2 += n + 1;

  /* Compare each query field in the first URI and ensure it appears
   * in the second URI.  Note the first URI is the one we passed to
   * libnbd, we're not worried about extra fields in the second URI.
   */
  while (*uri1) {
    char *q;

    n = strcspn (uri1, "&");
    q = strndup (uri1, n);
    if (q == NULL) { perror ("strndup"); exit (EXIT_FAILURE); }
    if (case_insensitive_substring (uri2, q))
      r = 0;
    else {
      fprintf (stderr, "error: compare_uris: query string '%s' does not appear "
               "in returned URI\n", q);
      r = 1;
    }
    free (q);
    if (r != 0)
      return r;
    if (strlen (uri1) == n)
      return 0;
    uri1 += n + 1;
  }

  return 0;
}
#endif /* SKIP_GET_URI */
