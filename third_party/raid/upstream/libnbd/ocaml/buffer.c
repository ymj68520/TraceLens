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

#include <config.h>

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#include <caml/alloc.h>
#include <caml/bigarray.h>
#include <caml/fail.h>
#include <caml/memory.h>
#include <caml/mlvalues.h>

#include <libnbd.h>

#include "iszero.h"

#include "nbd-c.h"

/* Copy an NBD persistent buffer to an OCaml bytes. */
value
nbd_internal_ocaml_buffer_to_bytes (value bufv)
{
  CAMLparam1 (bufv);
  CAMLlocal1 (rv);
  struct caml_ba_array *buf = Caml_ba_array_val (bufv);
  uint8_t *data = (uint8_t *)buf->data;
  size_t len = (size_t)buf->dim[0];

  rv = caml_alloc_string (len);
  memcpy (Bytes_val (rv), data, len);

  CAMLreturn (rv);
}

/* Copy an OCaml bytes into an NBD persistent buffer. */
value
nbd_internal_ocaml_buffer_of_bytes (value bytesv, value bufv)
{
  CAMLparam2 (bytesv, bufv);
  struct caml_ba_array *buf = Caml_ba_array_val (bufv);
  uint8_t *data = (uint8_t *)buf->data;
  size_t len = (size_t)buf->dim[0];

  memcpy (data, Bytes_val (bytesv), len);

  CAMLreturn (Val_unit);
}

/* Check buffer is zero. */
/* NB: noalloc function. */
value
nbd_internal_ocaml_is_zero (value optsub, value bufv)
{
  struct caml_ba_array *buf = Caml_ba_array_val (bufv);
  uint8_t *data = (uint8_t *)buf->data;
  size_t size = (size_t)buf->dim[0];
  size_t offset = 0, len = size;

  if (optsub != Val_int (0)) {               /* Some (offset, len) */
    value v = Field (optsub, 0);             /* (offset, len) */

    offset = Int_val (Field (v, 0));
    len = Int_val (Field (v, 1));
    if (offset < 0 || offset > size || len < 0 || len > size ||
        offset + len < 0 || offset + len > size)
      caml_invalid_argument ("NBD.Buffer.is_zero");
  }

  return Val_bool (is_zero ((void *) &data[offset], len));
}
