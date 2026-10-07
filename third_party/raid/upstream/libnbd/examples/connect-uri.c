/* This example shows how to connect to an NBD
 * server using the server's NBD URI.
 *
 * To test this with a recent version of nbdkit
 * that supports the '$uri' syntax, do:
 *
 * nbdkit -U - random 1M \
 *   --run './connect-uri $uri'
 *
 * To test connecting to a remote NBD server
 * listening on port 10809, do:
 *
 * ./connect-uri nbd://remote/
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <stdint.h>
#include <inttypes.h>

#include <libnbd.h>

int
main (int argc, char *argv[])
{
  struct nbd_handle *nbd;
  char *s;
  int64_t size;

  if (argc != 2) {
    fprintf (stderr, "usage: %s URI\n",
             argv[0]);
    exit (EXIT_FAILURE);
  }

  /* Create the libnbd handle. */
  nbd = nbd_create ();
  if (nbd == NULL) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }

  /* Request full information
   * (for nbd_get_canonical_export_name below)
   */
#if LIBNBD_HAVE_NBD_SET_FULL_INFO
  if (nbd_set_full_info (nbd, true) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
#endif

  /* Connect to the NBD URI. */
  printf ("connecting to %s ...\n", argv[1]);
  fflush (stdout);
  if (nbd_connect_uri (nbd, argv[1]) == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  printf ("connected\n");

  /* Print the URI, export name, size and other info. */
  printf ("requested URI: %s\n", argv[1]);
  s = nbd_get_uri (nbd);
  printf ("generated URI: %s\n", s ? s : "NULL");
  free (s);
  size = nbd_get_size (nbd);
  if (size == -1) {
    fprintf (stderr, "%s\n", nbd_get_error ());
    exit (EXIT_FAILURE);
  }
  printf ("size: %" PRIi64 "\n", size);
  s = nbd_get_export_name (nbd);
  printf ("requested export name: %s\n", s ? s : "NULL");
  free (s);
#if LIBNBD_HAVE_NBD_GET_CANONICAL_EXPORT_NAME
  s = nbd_get_canonical_export_name (nbd);
  printf ("canonical export name: %s\n", s ? s : "NULL");
  free (s);
#endif
#if LIBNBD_HAVE_NBD_GET_EXPORT_DESCRIPTION
  s = nbd_get_export_description (nbd);
  printf ("export description: %s\n", s ? s : "NULL");
  free (s);
#endif

  /* Close the libnbd handle. */
  nbd_close (nbd);

  exit (EXIT_SUCCESS);
}
