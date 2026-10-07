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

#ifndef NBDKIT_OCAML_PLUGIN_H
#define NBDKIT_OCAML_PLUGIN_H

#include <caml/version.h>

/* Replacement if caml_alloc_initialized_string is missing, added
 * to OCaml runtime in 2017.
 */
#ifndef HAVE_CAML_ALLOC_INITIALIZED_STRING
static inline value
caml_alloc_initialized_string (mlsize_t len, const char *p)
{
  value sv = caml_alloc_string (len);
  memcpy ((char *) String_val (sv), p, len);
  return sv;
}
#endif

/* To debug all runtime acquire/release, uncomment this section. */
#if 0
#define do_caml_acquire_runtime_system()                \
  do {                                                  \
    nbdkit_debug ("caml_acquire_runtime_system");       \
    caml_acquire_runtime_system ();                     \
  } while (0)
#define do_caml_release_runtime_system()                \
  do {                                                  \
    nbdkit_debug ("caml_release_runtime_system");       \
    caml_release_runtime_system ();                     \
  } while (0)
#else
#define do_caml_acquire_runtime_system() caml_acquire_runtime_system()
#define do_caml_release_runtime_system() caml_release_runtime_system()
#endif

/* For functions which call into OCaml code, call
 * caml_acquire_runtime_system ... caml_release_runtime_system around
 * the code.  This prevents other threads in the same domain running.
 * The macro ensures that the calls are paired properly.
 */
#define ACQUIRE_RUNTIME_FOR_CURRENT_SCOPE() \
  __attribute__ ((unused, cleanup (cleanup_release_runtime_system))) \
  int _unused;                                                       \
  do_caml_acquire_runtime_system ()
static inline void
cleanup_release_runtime_system (int *unused)
{
  do_caml_release_runtime_system ();
}

#endif /* NBDKIT_OCAML_PLUGIN_H */
