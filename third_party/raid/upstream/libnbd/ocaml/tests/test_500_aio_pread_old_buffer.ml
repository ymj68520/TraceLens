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

(* Note: Uses the old NBD.Buffer.t from libnbd <= 1.18 *)

open Ocaml_test_config

let expected =
  let b = Bytes.create 512 in
  for i = 0 to 512/8-1 do
    let i64 = Int64.of_int (i*8) in
    bytes_set_int64_be b (i*8) i64
  done;
  b

let () =
  let nbd = NBD.create () in
  NBD.connect_command nbd [nbdkit; "-s"; "--exit-with-parent"; "-v";
                           "pattern"; "size=512"];

  let buf = NBD.Buffer.alloc 512 in
  let cookie = NBD.aio_pread nbd buf 0_L in
  while not (NBD.aio_command_completed nbd cookie) do
    ignore (NBD.poll nbd (-1))
  done;

  let buf = NBD.Buffer.to_bytes buf in

  assert (buf = expected)

let () = Gc.compact ()
