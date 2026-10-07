/* nbd client library in userspace: state machine
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

/* State machine related to connecting with systemd socket activation. */

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <assert.h>
#include <sys/socket.h>
#include <sys/un.h>

#include "internal.h"
#include "compiler-macros.h"
#include "unique-name.h"
#include "array-size.h"
#include "checked-overflow.h"

/* This is baked into the systemd socket activation API. */
#define FIRST_SOCKET_ACTIVATION_FD 3

/* Describes a systemd socket activation environment variable. */
struct sact_var {
  const char *prefix; /* variable name and equal sign */
  size_t prefix_len;
  const char *value;
  size_t value_len;
};

/* Determine the length of a string, using "sizeof" whenever possible.
 *
 * Do not use this macro on an argument that has side effects, as no guarantees
 * are given regarding the number of times the argument may be evaluated.
 * TYPE_IS_ARRAY(s) itself may contribute a different number of evaluations
 * dependent on whether "s" has variably modified type, and then the conditional
 * operator either evaluates "sizeof s" (which contributes 0 or 1 evaluations,
 * dependent on whether "s" has variably modified type) or strlen(s) (which
 * contributes 1 evaluation). Also note that the argument of the "sizeof"
 * operator is *only* parenthesized because "s" is a macro parameter here.
*/
#define STRLEN1(s) ((TYPE_IS_ARRAY (s) ? sizeof (s) - 1 : strlen (s)))

/* Push a new element to an array of "sact_var" structures.
 *
 * "vars" is the array to extend. "num_vars" (of type (size_t *)) points to the
 * number of elements that the array, on input, contains; (*num_vars) is
 * increased by one on output. "prefix" and "value" serve as the values for
 * setting the fields in the new element. "ofs" (of type (size_t *)) may be
 * NULL; if it isn't, then on output, (*ofs) is set to the input value of
 * (*num_vars): the offset of the just-pushed element.
 *
 * Avoid arguments with side-effects here as well.
 */
#define SACT_VAR_PUSH(vars, num_vars, prefix, value, ofs)       \
  SACT_VAR_PUSH1 ((vars), (num_vars), (prefix), (value), (ofs), \
                  NBDKIT_UNIQUE_NAME (_ofs))
#define SACT_VAR_PUSH1(vars, num_vars, prefix, value, ofs, ofs1)             \
  do {                                                                       \
    size_t *ofs1;                                                            \
                                                                             \
    assert (*(num_vars) < ARRAY_SIZE (vars));                                \
    ofs1 = (ofs);                                                            \
    if (ofs1 != NULL)                                                        \
      *ofs1 = *(num_vars);                                                   \
    (vars)[(*(num_vars))++] = (struct sact_var){ (prefix), STRLEN1 (prefix), \
                                                 (value), STRLEN1 (value) }; \
  } while (0)

extern char **environ;

/* Prepare environment for calling execvp when doing systemd socket activation.
 * Takes the current environment and copies it. Removes any existing socket
 * activation variables and replaces them with new ones. Variables in "sact_var"
 * will be placed at the front of "env", preserving the order from "sact_var".
 */
static int
prepare_socket_activation_environment (string_vector *env,
                                       const struct sact_var *sact_var,
                                       size_t num_vars)
{
  const struct sact_var *var_end;
  char *new_var;
  const struct sact_var *var;
  size_t i;

  *env = (string_vector)empty_vector;

  /* Set the exclusive limit for loops over "sact_var". */
  var_end = sact_var + num_vars;

  /* New environment variable being constructed for "env". */
  new_var = NULL;

  /* Copy "sact_var" to the front of "env". */
  for (var = sact_var; var < var_end; ++var) {
    size_t new_var_size;
    char *p;

    /* Calculate the size of the "NAME=value" string. */
    if (ADD_OVERFLOW (var->prefix_len, var->value_len, &new_var_size) ||
        ADD_OVERFLOW (new_var_size, 1u, &new_var_size)) {
      errno = EOVERFLOW;
      goto err;
    }

    /* Allocate and format "NAME=value". */
    new_var = malloc (new_var_size);
    if (new_var == NULL)
      goto err;
    p = new_var;

    memcpy (p, var->prefix, var->prefix_len);
    p += var->prefix_len;

    memcpy (p, var->value, var->value_len);
    p += var->value_len;

    *p++ = '\0';

    /* Push "NAME=value" to the vector. */
    if (string_vector_append (env, new_var) == -1)
      goto err;
    /* Ownership transferred. */
    new_var = NULL;
  }

  /* Append the current environment to "env", but remove "sact_var". */
  for (i = 0; environ[i] != NULL; ++i) {
    for (var = sact_var; var < var_end; ++var) {
      if (strncmp (environ[i], var->prefix, var->prefix_len) == 0)
        break;
    }
    /* Drop known socket activation variable from the current environment. */
    if (var < var_end)
      continue;

    new_var = strdup (environ[i]);
    if (new_var == NULL)
      goto err;

    if (string_vector_append (env, new_var) == -1)
      goto err;
    /* Ownership transferred. */
    new_var = NULL;
  }

  /* The environ must be NULL-terminated. */
  if (string_vector_append (env, NULL) == -1)
    goto err;

  return 0;

 err:
  set_error (errno, "malloc");
  free (new_var);
  string_vector_empty (env);
  return -1;
}

STATE_MACHINE {
 CONNECT_SA.START:
  enum state next;
  char *tmpdir;
  char *sockpath;
  int s;
  struct sockaddr_un addr;
  struct execvpe execvpe_ctx;
  size_t num_vars;
  struct sact_var sact_var[3];
  size_t pid_ofs;
  string_vector env;
  pid_t pid;

  assert (!h->sock);
  assert (h->argv.ptr);
  assert (h->argv.ptr[0]);

  next = %.DEAD;

  /* Use /tmp instead of TMPDIR because we must ensure the path is
   * short enough to store in the sockaddr_un.  On some platforms this
   * may cause problems so we may need to revisit it.  XXX
   */
  tmpdir = strdup ("/tmp/libnbdXXXXXX");
  if (tmpdir == NULL) {
    set_error (errno, "strdup");
    goto done;
  }

  if (mkdtemp (tmpdir) == NULL) {
    set_error (errno, "mkdtemp");
    goto free_tmpdir;
  }

  if (asprintf (&sockpath, "%s/sock", tmpdir) == -1) {
    set_error (errno, "asprintf");
    goto rmdir_tmpdir;
  }

  s = nbd_internal_socket (AF_UNIX, SOCK_STREAM, 0, false);
  if (s == -1) {
    set_error (errno, "socket");
    goto free_sockpath;
  }

  addr.sun_family = AF_UNIX;
  memcpy (addr.sun_path, sockpath, strlen (sockpath) + 1);
  if (bind (s, (struct sockaddr *)&addr, sizeof addr) == -1) {
    set_error (errno, "bind: %s", sockpath);
    goto close_socket;
  }

  if (listen (s, SOMAXCONN) == -1) {
    set_error (errno, "listen");
    goto unlink_sockpath;
  }

  if (nbd_internal_execvpe_init (&execvpe_ctx, h->argv.ptr[0], h->argv.len) ==
      -1) {
    set_error (errno, "nbd_internal_execvpe_init");
    goto unlink_sockpath;
  }

  num_vars = 0;
  SACT_VAR_PUSH (sact_var, &num_vars,
                 "LISTEN_PID=", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", &pid_ofs);
  SACT_VAR_PUSH (sact_var, &num_vars,
                 "LISTEN_FDS=", "1", NULL);
  /* Push LISTEN_FDNAMES unconditionally. This ensures we overwrite any
   * inherited LISTEN_FDNAMES. If "h->sact_name" is NULL, then push
   * "LISTEN_FDNAMES=unknown"; it will have the same effect on the child process
   * as unsetting LISTEN_FDNAMES would (with LISTEN_FDS being set to 1):
   * <https://www.freedesktop.org/software/systemd/man/sd_listen_fds.html>.
   */
  SACT_VAR_PUSH (sact_var, &num_vars,
                 "LISTEN_FDNAMES=",
                 h->sact_name == NULL ? "unknown" : h->sact_name,
                 NULL);
  if (prepare_socket_activation_environment (&env, sact_var, num_vars) == -1)
    /* prepare_socket_activation_environment() calls set_error() internally */
    goto uninit_execvpe;

  pid = fork ();
  if (pid == -1) {
    set_error (errno, "fork");
    goto empty_env;
  }

  if (pid == 0) {         /* child - run command */
    if (s != FIRST_SOCKET_ACTIVATION_FD) {
      if (dup2 (s, FIRST_SOCKET_ACTIVATION_FD) == -1) {
        nbd_internal_fork_safe_perror ("dup2");
        _exit (126);
      }
      if (close (s) == -1) {
        nbd_internal_fork_safe_perror ("close");
        _exit (126);
      }
    }
    else {
      /* We must unset CLOEXEC on the fd.  (dup2 above does this
       * implicitly because CLOEXEC is set on the fd, not on the
       * socket).
       */
      int flags = fcntl (s, F_GETFD, 0);
      if (flags == -1) {
        nbd_internal_fork_safe_perror ("fcntl: F_GETFD");
        _exit (126);
      }
      if (fcntl (s, F_SETFD, (int)(flags & ~(unsigned)FD_CLOEXEC)) == -1) {
        nbd_internal_fork_safe_perror ("fcntl: F_SETFD");
        _exit (126);
      }
    }

    char buf[32];
    const char *v = nbd_internal_fork_safe_itoa (getpid (), buf, sizeof buf);
    NBD_INTERNAL_FORK_SAFE_ASSERT (strlen (v) <= sact_var[pid_ofs].value_len);
    strcpy (env.ptr[pid_ofs] + sact_var[pid_ofs].prefix_len, v);

    /* Restore SIGPIPE back to SIG_DFL. */
    if (signal (SIGPIPE, SIG_DFL) == SIG_ERR) {
      nbd_internal_fork_safe_perror ("signal");
      _exit (126);
    }

    (void)nbd_internal_fork_safe_execvpe (&execvpe_ctx, &h->argv, env.ptr);
    nbd_internal_fork_safe_perror (h->argv.ptr[0]);
    if (errno == ENOENT)
      _exit (127);
    else
      _exit (126);
  }

  /* Parent -- we're done; commit. */
  h->sact_tmpdir = tmpdir;
  h->sact_sockpath = sockpath;
  h->pid = pid;

  h->connaddrlen = sizeof addr;
  memcpy (&h->connaddr, &addr, h->connaddrlen);
  next = %^CONNECT.START;

  /* fall through, for releasing the temporaries */

empty_env:
  string_vector_empty (&env);

uninit_execvpe:
  nbd_internal_execvpe_uninit (&execvpe_ctx);

unlink_sockpath:
  if (next == %.DEAD)
    unlink (sockpath);

close_socket:
  close (s);

free_sockpath:
  if (next == %.DEAD)
    free (sockpath);

rmdir_tmpdir:
  if (next == %.DEAD)
    rmdir (tmpdir);

free_tmpdir:
  if (next == %.DEAD)
    free (tmpdir);

done:
  SET_NEXT_STATE (next);
  return 0;
} /* END STATE MACHINE */
