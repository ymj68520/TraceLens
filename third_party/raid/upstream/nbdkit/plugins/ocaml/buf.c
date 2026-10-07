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
#include <stdint.h>
#include <string.h>

#include <caml/bigarray.h>
#include <caml/mlvalues.h>

#define NBDKIT_API_VERSION 2
#include <nbdkit-plugin.h>

/* Bindings for 'buf' type.
 *
 * We found that ocamlopt generated pretty poor code for copying into
 * a Bigarray.
 * https://discuss.ocaml.org/t/is-there-a-simple-library-that-wraps-a-c-mallocd-char-buffer/14323/12
 */

/* Workaround for OCaml < 4.06.0 */
#ifndef Bytes_val
#define Bytes_val(x) String_val (x)
#endif

/* NB: noalloc function. */
NBDKIT_DLL_PUBLIC value
ocaml_nbdkit_blit_from (value srcv, value src_posv,
                        value bufv, value buf_posv,
                        value lenv)
{
  const char *src = String_val (srcv);
  int src_pos = Int_val (src_posv);
  struct caml_ba_array *buf = Caml_ba_array_val (bufv);
  uint8_t *data = (uint8_t *)buf->data;
  int buf_pos = Int_val (buf_posv);
  int len = Int_val (lenv);

  memcpy (&data[buf_pos], &src[src_pos], len);
  return Val_unit;
}

/* NB: noalloc function. */
NBDKIT_DLL_PUBLIC value
ocaml_nbdkit_blit_to_bytes (value bufv, value buf_posv,
                            value dstv, value dst_posv,
                            value lenv)
{
  struct caml_ba_array *buf = Caml_ba_array_val (bufv);
  uint8_t *data = (uint8_t *)buf->data;
  int buf_pos = Int_val (buf_posv);
  char *dst = (char *) Bytes_val (dstv);
  int dst_pos = Int_val (dst_posv);
  int len = Int_val (lenv);

  memcpy (&dst[dst_pos], &data[buf_pos], len);
  return Val_unit;
}
