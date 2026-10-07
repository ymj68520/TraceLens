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

(* Test lifetime of NBD.Buffer.t. *)

open Ocaml_test_config

let () =
  let nbd = NBD.create () in
  NBD.connect_command nbd [nbdkit; "-s"; "--exit-with-parent"; "-v";
                           "pattern"; "size=32M"];

  (* Choose a large read size so that it won't usually complete during
   * the call to aio_pread.
   *)
  let size = 16 * 1024 * 1024 in

  (* Allocate a temporary buffer but don't keep a reference to it.
   * The wrapper around aio_pread should register a root here
   * so that it won't be freed.
   *)
  let cookie = NBD.aio_pread nbd (NBD.Buffer.alloc size) 0_L in

  (* Hopefully the operation is still running, so the buffer is
   * still required.  Let's run a full GC cycle now.  If the
   * buffer is (incorrectly) freed here, we should crash or
   * valgrind will give an error.
   *)
  Gc.compact ();

  (* Complete the operation.  The aio_pread completion callback
   * should unregister the root.
   *)
  while not (NBD.aio_command_completed nbd cookie) do
    ignore (NBD.poll nbd (-1))
  done;

  (* Run a GC cycle again.  The buffer may now be freed. *)
  Gc.compact ()
