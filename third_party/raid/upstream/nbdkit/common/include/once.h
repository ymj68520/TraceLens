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

#ifndef NBDKIT_ONCE_H
#define NBDKIT_ONCE_H

#ifdef HAVE_STDATOMIC_H
#include <stdatomic.h>
#else
/* This is best effort on platforms that don't support atomic.
 * 32 bit ints are generally fine in reality.
 */
#define _Atomic /**/
#endif

#include "unique-name.h"

/* Run the statement once (per nbdkit run). */
#define ONCE(stmt) ONCE_1(NBDKIT_UNIQUE_NAME(_once), (stmt))

/* The actual implementation:
 *
 * The comparison with 0 avoids var wrapping around.  Mostly var will
 * only be 0 or 1, or in rare cases other small integers.
 *
 * The atomic increment & comparison with 1 is what only allows a
 * single thread to run the statement.
 *
 * To avoid optimisations: Use 'volatile' so reads and writes are not
 * removed, and use 'unsigned' to avoid any with signed overflow.
 */
#define ONCE_1(var, stmt)                       \
  do {                                          \
    static volatile _Atomic unsigned var = 0;   \
    if (var == 0 && ++var == 1) { stmt; }       \
  } while (0)

#endif /* NBDKIT_ONCE_H */
