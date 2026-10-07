(* hey emacs, this is OCaml code: -*- tuareg -*- *)
(* nbd client library in userspace: generator
 * Copyright Tage Johansson
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

(* Low level Rust bindings for the libnbd-sys crate. *)

open Printf
open API
open Utils

(** A list of the argument types corresponding to an [arg]. *)
let arg_types : arg -> string list = function
  | Bool n -> [ "bool" ]
  | Int n | Fd n | Enum (n, _) -> [ "c_int" ]
  | UInt n -> [ "c_uint" ]
  | UIntPtr n -> [ "uintptr_t" ]
  | SizeT n -> [ "size_t" ]
  | UInt32 n | Flags (n, _) -> [ "u32" ]
  | Int64 n -> [ "i64" ]
  | UInt64 n -> [ "u64" ]
  | String n | Path n -> [ "*const c_char" ]
  | SockAddrAndLen (n1, n2) -> [ "*const sockaddr"; "socklen_t" ]
  | StringList n -> [ "*mut *mut c_char" ]
  | BytesIn (n1, n2) | BytesPersistIn (n1, n2) -> [ "*const c_void"; "usize" ]
  | BytesOut (n1, n2) | BytesPersistOut (n1, n2) -> [ "*mut c_void"; "usize" ]
  | Closure { cbname } -> [ sprintf "nbd_%s_callback" cbname ]
  | Extent64 (_) -> [ "nbd_extent" ]

(** The type of an optional argument. *)
let optarg_type : optarg -> string = function
  | OClosure { cbname } -> sprintf "nbd_%s_callback" cbname
  | OFlags _ -> "u32"

(** The types of arguments corresponding to a [cbarg]. *)
let cbarg_types : cbarg -> string list = function
  | CBInt n -> arg_types (Int n)
  | CBUInt n -> arg_types (UInt n)
  | CBInt64 n -> arg_types (Int64 n)
  | CBUInt64 n -> arg_types (UInt64 n)
  | CBString n -> arg_types (String n)
  | CBBytesIn (n1, n2) -> arg_types (BytesIn (n1, n2))
  | CBMutable arg -> arg_types arg |> List.map (fun x -> "*mut " ^ x)
  | CBArrayAndLen (elem, _) ->
      let elem_type =
        match arg_types elem with
        | [ x ] -> x
        | _ -> failwith "Bad array element type"
      in
      [ sprintf "*mut %s" elem_type; "usize" ]

(** Get a return type. *)
let ret_type : ret -> string = function
  | RBool -> "c_int"
  | RStaticString -> "*const c_char"
  | RInt | RErr | RFd | REnum _ -> "c_int"
  | RInt64 | RCookie -> "i64"
  | RSizeT -> "isize"
  | RString -> "*mut c_char"
  | RUInt -> "c_uint"
  | RUInt64 -> "u64"
  | RUIntPtr -> "uintptr_t"
  | RFlags _ -> "u32"

(** The names of all arguments corresponding to an [arg]. *)
let arg_names : arg -> string list = function
  | Bool n
  | Int n
  | UInt n
  | UIntPtr n
  | UInt32 n
  | Int64 n
  | UInt64 n
  | SizeT n
  | String n
  | StringList n
  | Path n
  | Fd n
  | Enum (n, _)
  | Flags (n, _)
  | Closure { cbname = n } ->
      [ n ]
  | SockAddrAndLen (n1, n2)
  | BytesIn (n1, n2)
  | BytesPersistIn (n1, n2)
  | BytesOut (n1, n2)
  | BytesPersistOut (n1, n2) ->
      [ n1; n2 ]
  | Extent64 _ -> assert false (* only used in extent64_closure *)

(** The name of an optional argument. *)
let optarg_name : optarg -> string = function
  | OClosure { cbname = name } | OFlags (name, _, _) -> name

(** Print the struct for a closure. *)
let print_closure_struct { cbname; cbargs } =
  pr "#[repr(C)]\n";
  pr "#[derive(Debug, Clone, Copy)]\n";
  pr "pub struct nbd_%s_callback {\n" cbname;
  pr "    pub callback: \n";
  pr "      Option<unsafe extern \"C\" fn(*mut c_void, %s) -> c_int>,\n"
    (cbargs |> List.map cbarg_types |> List.flatten |> String.concat ", ");
  pr "    pub user_data: *mut c_void,\n";
  pr "    pub free: Option<unsafe extern \"C\" fn(*mut c_void)>,\n";
  pr "}\n"

(** Print an "extern definition" for a handle call. *)
let print_handle_call (name, call) =
  let args_names =
    (call.args |> List.map arg_names |> List.flatten)
    @ (call.optargs |> List.map optarg_name)
  in
  let args_types =
    (call.args |> List.map arg_types |> List.flatten)
    @ (call.optargs |> List.map optarg_type)
  in
  pr "pub fn nbd_%s(handle: *mut nbd_handle, %s) -> %s;\n" name
    (List.map2 (fun n ty -> sprintf "%s: %s" n ty) args_names args_types
    |> String.concat ", ")
    (ret_type call.ret)

(** Print a definition of "nbd_handle" and "nbd_extent" types. *)
let print_types () =
  pr "#[repr(C)]\n";
  pr "#[derive(Debug, Clone, Copy)]\n";
  pr "pub struct nbd_handle {\n";
  pr "    _unused: [u8; 0],\n";
  pr "}\n";
  pr "\n";
  pr "#[repr(C)]\n";
  pr "#[derive(Debug, Clone, Copy)]\n";
  pr "pub struct nbd_extent {\n";
  pr "    length: u64,\n";
  pr "    flags: u64,\n";
  pr "}\n";
  pr "\n"

(** Print some more "extern definitions". *)
let print_more_defs () =
  pr "extern \"C\" {\n";
  pr "pub fn nbd_get_error() -> *const c_char;\n";
  pr "pub fn nbd_get_errno() -> c_int;\n";
  pr "pub fn nbd_create() -> *mut nbd_handle;\n";
  pr "pub fn nbd_close(h: *mut nbd_handle);\n";
  pr "}\n";
  pr "\n"

let print_imports () =
  pr "use libc::*;\n";
  pr "use std::ffi::c_void;\n";
  pr "\n"

let generate_rust_sys_bindings () =
  generate_header CStyle ~copyright:"Tage Johansson";
  pr "\n";
  print_imports ();
  print_types ();
  print_more_defs ();
  all_closures |> List.iter print_closure_struct;
  pr "extern \"C\" {\n";
  handle_calls |> List.iter print_handle_call;
  pr "}\n\n"
