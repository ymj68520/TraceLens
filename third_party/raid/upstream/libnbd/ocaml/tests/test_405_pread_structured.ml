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

open Printf

let expected =
  let b = Bytes.create 512 in
  for i = 0 to 512/8-1 do
    let i64 = Int64.of_int (i*8) in
    bytes_set_int64_be b (i*8) i64
  done;
  b

(* This can be any error, it's just used as a sentinel. *)
let test_error = Unix.ENETDOWN

let f user_data buf2 offset s err =
  assert (!err = 0);
  err := NBD.errno_of_unix_error test_error;
  if user_data <> 42 then invalid_arg "this should be turned into NBD.Error";
  assert (buf2 = expected);
  assert (offset = 0_L);
  assert (s = Int32.to_int NBD.read_data);
  0

let () =
  let nbd = NBD.create () in
  NBD.connect_command nbd
                      [nbdkit; "-s"; "--exit-with-parent"; "-v";
                       "pattern"; "size=512"];
  let buf = Bytes.create 512 in

  NBD.pread_structured nbd buf 0_L (f 42);
  assert (buf = expected);

  let flags = let open NBD.CMD_FLAG in [DF] in
  NBD.pread_structured nbd buf 0_L (f 42) ~flags;
  assert (buf = expected);

  try
    NBD.pread_structured nbd buf 0_L (f 43) ~flags;
    assert false
  with
   | NBD.Error (_, Some errno) when errno = test_error -> ()
   | NBD.Error (_, _) -> assert false

let () = Gc.compact ()
