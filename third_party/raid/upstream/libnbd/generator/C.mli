(* hey emacs, this is OCaml code: -*- tuareg -*- *)
(* nbd client library in userspace: generate the C API and documentation
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

type closure_style = Direct | AddressOf | Pointer
type parens_style = NoParens | ParensSameLine | ParensNewLineWithIndent of int

val generate_lib_libnbd_syms : unit -> unit
val generate_include_libnbd_h : unit -> unit
val generate_lib_unlocked_h : unit -> unit
val generate_lib_api_c : unit -> unit

val name_of_arg : API.arg -> string list
val name_of_optarg : API.optarg -> string
val arg_attr_nonnull : API.arg -> bool list
val optarg_attr_nonnull : API.optarg -> bool list
val print_arg_list : ?wrap:bool -> ?maxcol:int ->
                     ?handle:bool -> ?types:bool -> ?parens:parens_style ->
                     ?closure_style:closure_style ->
                     API.arg list -> API.optarg list -> unit
val print_cbarg_list : ?wrap:bool -> ?maxcol:int ->
                       ?types:bool -> ?parens:bool -> ?noconst:bool ->
                       API.cbarg list -> unit
val print_call : ?wrap:bool -> ?maxcol:int ->
                 ?closure_style:closure_style ->
                 string -> API.arg list -> API.optarg list -> API.ret -> unit
val errcode_of_ret : API.ret -> string option
val type_of_ret : API.ret -> string
