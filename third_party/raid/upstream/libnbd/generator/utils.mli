(* hey emacs, this is OCaml code: -*- tuareg -*- *)
(* nbd client library in userspace: utilities
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

(* Helper functions. *)

type comment_style =
  | CStyle
  | CPlusPlusStyle
  | HashStyle
  | OCamlStyle
  | HaskellStyle
  | PODCommentStyle

type chan = NoOutput | OutChannel of out_channel | Buffer of Buffer.t

type location = string * int  (** source location: file, line number *)

val failwithf : ('a, unit, string, 'b) format4 -> 'a

val filter_map : ('a -> 'b option) -> 'a list -> 'b list
val group_by : ('a * 'b) list -> ('a * 'b list) list
val uniq : ?cmp:('a -> 'a -> int) -> 'a list -> 'a list
val is_prefix : string -> string -> bool
val find : string -> string -> int
val split : string -> string -> string * string
val nsplit : string -> string -> string list
val char_mem : char -> string -> bool
val span : string -> string -> int
val cspan : string -> string -> int
val string_starts_with : prefix:string -> string -> bool
val array_find_map : ('a -> 'b option) -> 'a array -> 'b option
val option_map : ('a -> 'b) -> 'a option -> 'b option
val quote : string -> string
val spaces : int -> string
val macro_name : string -> string
val files_equal : string -> string -> bool

val generate_header :
  ?extra_sources:string list -> ?copyright:string -> comment_style -> unit

(** Type of code formatter. *)
type formatter =
  | Gofmt
  | Rustfmt

(** Redirect stdout to a file. Possibly formatting the code. *)
val output_to : ?formatter:formatter option -> string -> (unit -> 'a) -> unit

val pr : ('a, unit, string, unit) format4 -> 'a
val pr_wrap : ?maxcol:int -> char -> (unit -> 'a) -> unit
val pr_wrap_cstr : ?maxcol:int -> (unit -> 'a) -> unit
val pr_wrap_c_comment : ?maxcol:int -> (unit -> 'a) -> unit
val output_lineno : unit -> int
val output_column : unit -> int

val noloc : location
val string_of_location : location -> string
val line_directive_of_location : location -> string

type cache_key = string
type cache_value = string list
val pod2text : cache_key -> cache_value

(* Convert C function name to upper-camel-case name. *)
val camel_case : string -> string
