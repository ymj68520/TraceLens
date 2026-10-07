/* nbd client library in userspace
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
#include <string.h>

#include "libnbd.h"
#include "version.h"

void
display_version (const char *program_name)
{
  struct nbd_handle *nbd;
  const char *package_name = NULL;
  const char *version = NULL;
  const char *version_extra = NULL;

  /* The program name and the version of the binary. */
  printf ("%s %s", program_name, PACKAGE_VERSION);
  if (strcmp (LIBNBD_VERSION_EXTRA, "") != 0)
    printf (" (%s)", LIBNBD_VERSION_EXTRA);
  printf ("\n");

  /* Flush to make sure it is printed, even if the code below crashes
   * for any reason.
   */
  fflush (stdout);

  /* Now try to get the name and version of libnbd from the shared
   * library, but try not to fail.
   */
  nbd = nbd_create ();
  if (nbd) {
    package_name = nbd_get_package_name (nbd);
    version = nbd_get_version (nbd);
    version_extra = nbd_get_version_extra (nbd);
  }
  if (version) {
    printf ("%s %s", package_name ? package_name : PACKAGE_NAME, version);
    if (strcmp (version_extra, "") != 0)
      printf (" (%s)", version_extra);
    printf ("\n");
    fflush (stdout);
  }
  nbd_close (nbd);
}
