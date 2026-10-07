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

#include <caml/alloc.h>
#include <caml/callback.h>
#include <caml/fail.h>
#include <caml/memory.h>
#include <caml/mlvalues.h>
#include <caml/threads.h>

#include <libnbd.h>

#include "nbd-c.h"

value
nbd_internal_ocaml_nbd_create (value unitv)
{
  CAMLparam1 (unitv);
  CAMLlocal1 (rv);
  struct nbd_handle *h;

  h = nbd_create ();
  if (h == NULL)
    nbd_internal_ocaml_raise_error ();

  rv = Val_nbd (h);
  CAMLreturn (rv);
}

value
nbd_internal_ocaml_nbd_close (value hv)
{
  CAMLparam1 (hv);
  struct nbd_handle *h = NBD_val (hv);

  if (h) {
    /* So we don't double-free. */
    NBD_val (hv) = NULL;

    caml_enter_blocking_section ();
    nbd_close (h);
    caml_leave_blocking_section ();
  }

  CAMLreturn (Val_unit);
}
