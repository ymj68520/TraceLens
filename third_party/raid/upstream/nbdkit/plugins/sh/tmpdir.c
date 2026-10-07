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
#include <string.h>
#include <unistd.h>

#include <nbdkit-plugin.h>

#include "cleanup.h"
#include "utils.h"

#include "tmpdir.h"

#ifndef HAVE_ENVIRON_DECL
extern char **environ;
#endif

char *tmpdir;
char **env;

void
tmpdir_load (void)
{
  /* Create the temporary directory for the shell script to use. */
  tmpdir = make_temporary_directory ();
  if (!tmpdir) {
    nbdkit_error ("mkdtemp: /tmp: %m");
    exit (EXIT_FAILURE);
  }

  nbdkit_debug ("load: tmpdir: %s", tmpdir);

  /* Copy the environment, and add $tmpdir. */
  env = copy_environ (environ, "tmpdir", tmpdir, NULL);
  if (env == NULL)
    exit (EXIT_FAILURE);
}

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-result"
void
tmpdir_unload (void)
{
  CLEANUP_FREE char *cmd = NULL;
  size_t i;

  /* Delete the temporary directory.  Ignore all errors. */
  if (asprintf (&cmd, "rm -rf %s", tmpdir) >= 0)
    system (cmd);
  free (tmpdir);

  /* Free the private copy of environ. */
  for (i = 0; env[i] != NULL; ++i)
    free (env[i]);
  free (env);
}
#pragma GCC diagnostic pop
