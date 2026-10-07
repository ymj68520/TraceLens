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
#include <signal.h>
#include <time.h>
#include <assert.h>

#include "internal.h"

#ifdef HAVE_TIMEOUT_OPTION

#include <sys/socket.h>

static void
connection_timeout (union sigval si)
{
  struct connection *conn = si.sival_ptr;

  assert (conn != NULL);

  debug ("connection timed out");

  /* Note this is called asynchronously from a different thread,
   * making it difficult to do this safely.  The theory here is that
   * since all connection operations are protected by a lock, we'll
   * take that lock and check that conn->magic is valid (to ensure it
   * hasn't been freed already).  However we still must do the minimum
   * possible, since raw socket or gnutls operations may be taking
   * place simultaneously.  The safest seems to be just to call
   * shutdown(2) on the socket.  Calling close(2) is less safe as it
   * might cause fd reuse.
   */
  lock_connection ();
  if (conn->magic == CONN_MAGIC &&
      conn->timer_set &&
      conn->status == STATUS_ACTIVE &&
      conn->sockout >= 0) {
    shutdown (conn->sockout, SHUT_RDWR);
    conn->status = STATUS_DEAD;
  }
  unlock_connection ();
}

int
start_timeout (struct connection *conn)
{
  if (timeout_secs == 0 && timeout_nsecs == 0)
    return 0;

  struct sigevent sev = {
    .sigev_notify = SIGEV_THREAD,
    .sigev_value.sival_ptr = conn,
    .sigev_notify_function = connection_timeout,
  };
  struct itimerspec its = {
    .it_value.tv_sec = timeout_secs,
    .it_value.tv_nsec = timeout_nsecs,
    .it_interval.tv_sec = 0, /* 0 = don't repeat */
    .it_interval.tv_nsec = 0,
  };

  if (timer_create (CLOCK_MONOTONIC, &sev, &conn->timer) == -1) {
    nbdkit_error ("timeout: timer_create: %m");
    return -1;
  }

  if (timer_settime (conn->timer, 0, &its, NULL) == -1) {
    nbdkit_error ("timeout: timer_settime: %m");
    timer_delete (conn->timer);
    return -1;
  }

  /* timer_t is actually a void * in glibc, but there seems to be no
   * guarantee that '0' means "no timer" (eg. if it was an integral
   * type in a different implementation).  Therefore record that we
   * set it and will need to delete it later.
   */
  conn->timer_set = true;

  return 0;
}

void
cancel_timeout (struct connection *conn)
{
  if (timeout_secs == 0 && timeout_nsecs == 0)
    return;

  if (conn->timer_set) {
    timer_delete (conn->timer);
    conn->timer_set = false;
  }
}

#else /* !HAVE_TIMEOUT_OPTION */

int
start_timeout (struct connection *conn)
{
  return 0;
}

void
cancel_timeout (struct connection *conn)
{
  return;
}

#endif /* !HAVE_TIMEOUT_OPTION */
