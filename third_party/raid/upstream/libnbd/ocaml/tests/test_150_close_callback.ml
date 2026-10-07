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

let () =
  let a = ref 0 and b = ref 0 in
  let nbd1 = NBD.create () and nbd2 = NBD.create () in

  NBD.add_close_callback nbd1 (fun () -> a := 1; 0);
  NBD.add_close_callback nbd1 (fun () -> b := 2; 0);
  NBD.add_close_callback nbd2 (fun () -> a := 2; 0);

  assert (!a = 0);
  assert (!b = 0);

  NBD.close nbd1;
  assert (!a = 1);
  assert (!b = 2);

  NBD.close nbd2;
  assert (!a = 2);
  assert (!b = 2)

let () = Gc.compact ()
