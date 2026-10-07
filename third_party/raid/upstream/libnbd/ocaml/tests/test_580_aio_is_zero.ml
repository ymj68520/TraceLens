(* hey emacs, this is OCaml code: -*- tuareg -*- *)
(* libnbd OCaml test case
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
 *)

open Ocaml_test_config

let () =
  let str0 = String.make 512 '\000' in
  let buf0 = NBD.Buffer.of_string str0 in
  assert (NBD.Buffer.is_zero buf0);
  assert (NBD.Buffer.is_zero ~sub:(0, 512) buf0);
  assert (NBD.Buffer.is_zero ~sub:(0, 256) buf0);
  assert (NBD.Buffer.is_zero ~sub:(256, 256) buf0);
  assert (NBD.Buffer.is_zero ~sub:(0, 0) buf0);
  assert (NBD.Buffer.is_zero ~sub:(0, 1) buf0);
  assert (NBD.Buffer.is_zero ~sub:(256, 1) buf0);
  assert (NBD.Buffer.is_zero ~sub:(256, 0) buf0);
  assert (NBD.Buffer.is_zero ~sub:(512, 0) buf0);

  let str1 = String.make 512 '\001' in
  let buf1 = NBD.Buffer.of_string str1 in
  assert (not (NBD.Buffer.is_zero buf1));
  assert (not (NBD.Buffer.is_zero ~sub:(0, 512) buf1));
  assert (not (NBD.Buffer.is_zero ~sub:(0, 256) buf1));
  assert (not (NBD.Buffer.is_zero ~sub:(256, 256) buf1));
  assert (not (NBD.Buffer.is_zero ~sub:(0, 1) buf1));
  assert (not (NBD.Buffer.is_zero ~sub:(256, 1) buf1));

  let buf2 = NBD.Buffer.of_string (str0 ^ str1) in
  assert (not (NBD.Buffer.is_zero buf2));
  assert (NBD.Buffer.is_zero ~sub:(0, 512) buf2);
  assert (not (NBD.Buffer.is_zero ~sub:(512, 512) buf2))

let () = Gc.compact ()
