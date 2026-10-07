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

(* Rust language bindings. *)

open Printf
open API
open Utils

(* The type for a set of names. *)
module NameSet = Set.Make (String)

(* List of handle calls which should not be part of the public API. This could
   for instance be `set_debug` and `set_debug_callback` which are handled
   separately by the log crate *)
let hidden_handle_calls : NameSet.t =
  NameSet.of_list
    [ "get_debug"; "set_debug"; "set_debug_callback"; "clear_debug_callback" ]

let print_rust_constant (name, value) =
  pr "pub const %s: u32 = %d;\n" name value

let print_rust_enum enum =
  pr "#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]\n";
  pr "#[repr(isize)]";
  pr "pub enum %s {\n" (camel_case enum.enum_prefix);
  List.iter
    (fun (name, num) -> pr "    %s = %d,\n" (camel_case name) num)
    enum.enums;
  pr "}\n\n"

(* Print a Rust struct for a set of flags. *)
let print_rust_flags { flag_prefix; flags } =
  pr "bitflags! {\n";
  pr "    #[repr(C)]\n";
  pr "    #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]\n";
  pr "    pub struct %s: u32 {\n" (camel_case flag_prefix);
  List.iter
    (fun (name, value) -> pr "        const %s = %d;\n" name value)
    flags;
  pr "    }\n";
  pr "}\n\n"

(* Convert a string to upper snake case. *)
let rec to_upper_snake_case s =
  let s = String.uppercase_ascii s in
  let s = explode s in
  let s = filter_map (
    function
    |'-' -> Some "_" | ':' -> None
    | ch -> Some (String.make 1 ch)
  ) s in
  String.concat "" s

(* Split a string into a list of chars.  In later OCaml we could
 * use Seq here, but that didn't exist in OCaml 4.05.
 *)
and explode str =
  let r = ref [] in
  for i = 0 to String.length str - 1 do
    let c = String.unsafe_get str i in
    r := c :: !r;
  done;
  List.rev !r

(* Print metadata namespaces. *)
let print_metadata_namespace (ns, ctxts) =
  pr "pub const NAMESPACE_%s: &[u8] = b\"%s:\";\n" (to_upper_snake_case ns) ns;
  ctxts
  |> List.iter (fun (ctxt, consts) ->
         let s = ns ^ ":" ^ ctxt in
         pr "pub const CONTEXT_%s_%s: &[u8] = b\"%s\";\n"
           (to_upper_snake_case ns)
           (to_upper_snake_case ctxt)
           s;
         consts
         |> List.iter (fun (n, i) ->
                pr "pub const %s: u32 = %d;\n" (to_upper_snake_case n) i))

(* Get the name of a rust argument. *)
let rust_arg_name : arg -> string = function
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
  | Extent64 n
  | Flags (n, _)
  | SockAddrAndLen (n, _)
  | BytesIn (n, _)
  | BytesPersistIn (n, _)
  | BytesOut (n, _)
  | BytesPersistOut (n, _)
  | Closure { cbname = n } ->
      n

(* Get the name of a rust optional argument. *)
let rust_optarg_name : optarg -> string = function
  | OClosure { cbname = n } | OFlags (n, _, _) -> n

(* Get the name of a Rust closure argument. *)
let rust_cbarg_name : cbarg -> string = function
  | CBInt n | CBUInt n | CBInt64 n | CBUInt64 n | CBString n | CBBytesIn (n, _)
    ->
      n
  | CBArrayAndLen (arg, _) | CBMutable arg -> rust_arg_name arg

(* Get the Rust type for an argument. *)
let rec rust_arg_type : arg -> string = function
  | Bool _ -> "bool"
  | Int _ -> "c_int"
  | UInt _ -> "c_uint"
  | UIntPtr _ -> "usize"
  | UInt32 _ -> "u32"
  | Int64 _ -> "i64"
  | UInt64 _ -> "u64"
  | SizeT _ -> "usize"
  | String _ -> "impl Into<Vec<u8>>"
  | SockAddrAndLen _ -> "SocketAddr"
  | StringList _ -> "impl IntoIterator<Item = impl AsRef<[u8]>>"
  | Path _ -> "impl Into<PathBuf>"
  | Enum (_, { enum_prefix = name }) | Flags (_, { flag_prefix = name }) ->
      camel_case name
  | Fd _ -> "OwnedFd"
  | BytesIn _ -> "&[u8]"
  | BytesOut _ -> "&mut [u8]"
  | BytesPersistIn _ -> "&'static [u8]"
  | BytesPersistOut _ -> "&'static mut [u8]"
  | Closure { cbargs } -> "impl " ^ rust_closure_trait cbargs
  | Extent64 _ -> "NbdExtent"

(* Get the Rust closure trait for a callback, That is `Fn*(...) -> ...)`. *)
and rust_closure_trait ?(lifetime = Some "'static") cbargs : string =
  let rust_cbargs = String.concat ", " (List.map rust_cbarg_type cbargs)
  and lifetime_constraint =
    match lifetime with None -> "" | Some x -> " + " ^ x
  in
  "FnMut(" ^ rust_cbargs ^ ") -> c_int + Send + Sync" ^ lifetime_constraint

(* Get the Rust type for a callback argument. *)
and rust_cbarg_type : cbarg -> string = function
  | CBInt n -> rust_arg_type (Int n)
  | CBUInt n -> rust_arg_type (UInt n)
  | CBInt64 n -> rust_arg_type (Int64 n)
  | CBUInt64 n -> rust_arg_type (UInt64 n)
  | CBString n -> "&[u8]"
  | CBBytesIn (n1, n2) -> rust_arg_type (BytesIn (n1, n2))
  | CBArrayAndLen (elem, _) -> "&[" ^ rust_arg_type elem ^ "]"
  | CBMutable arg -> "&mut " ^ rust_arg_type arg

(* Get the type of a rust optional argument. *)
let rust_optarg_type : optarg -> string = function
  | OClosure x -> sprintf "Option<%s>" (rust_arg_type (Closure x))
  | OFlags (name, flags, _) ->
      sprintf "Option<%s>" (rust_arg_type (Flags (name, flags)))

(* Given an argument, produce a list of names for arguments in FFI functions
   corresponding to that argument. Most arguments will just produce one name
   for one FFI argument, but for example [BytesIn] requires two separate FFI
   arguments hence a list is produced. *)
let ffi_arg_names : arg -> string list = function
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
      [ n ^ "_ffi" ]
  | SockAddrAndLen (n1, n2)
  | BytesIn (n1, n2)
  | BytesPersistIn (n1, n2)
  | BytesOut (n1, n2)
  | BytesPersistOut (n1, n2) ->
      [ n1 ^ "_ffi"; n2 ^ "_ffi" ]
  | Extent64 _ -> assert false (* only used in extent64_closure *)

let ffi_optarg_name : optarg -> string = function
  | OClosure { cbname = name } | OFlags (name, _, _) -> name ^ "_ffi"

(* Given a closure argument, produce a list of names used by FFI functions for
   that particular argument. Most closure arguments will just produce one FFI
   argument, but for instance [CBArrayAndLen] will produce two, hence we
   return a list. *)
let ffi_cbarg_names : cbarg -> string list = function
  | CBInt n | CBUInt n | CBInt64 n | CBUInt64 n | CBString n -> [ n ^ "_ffi" ]
  | CBBytesIn (n1, n2) -> [ n1 ^ "_ffi"; n2 ^ "_ffi" ]
  | CBArrayAndLen (arg, len) -> [ rust_arg_name arg ^ "_ffi"; len ^ "_ffi" ]
  | CBMutable arg -> [ rust_arg_name arg ^ "_ffi" ]

(* Given a closure argument, produce a list of types used by FFI functions for
   that particular argument. Most closure arguments will just produce one FFI
   argument, but for instance [CBArrayAndLen] will produce two, hence we
   return a list. *)
let ffi_cbarg_types : cbarg -> string list = function
  | CBInt _ -> [ "c_int" ]
  | CBUInt _ -> [ "c_uint" ]
  | CBInt64 _ -> [ "i64" ]
  | CBUInt64 _ -> [ "u64" ]
  | CBString _ -> [ "*const c_char" ]
  | CBBytesIn _ -> [ "*const c_void"; "usize" ]
  | CBArrayAndLen (UInt32 _, _) -> [ "*mut u32"; "usize" ]
  | CBArrayAndLen (Extent64 _, _) -> [ "*mut nbd_extent"; "usize" ]
  | CBArrayAndLen _ ->
      failwith
        "generator/Rust.ml: in ffi_cbarg_types: Unsupported type of array \
         element."
  | CBMutable (Int _) -> [ "*mut c_int" ]
  | CBMutable _ ->
      failwith
        "generator/Rust.ml: in ffi_cbarg_types: Unsupported type of mutable \
         argument."

(* Return type for a Rust function. *)
let rust_ret_type call : string =
  let core_type =
    match call.ret with
    | RBool -> "bool"
    | RStaticString -> "&'static [u8]"
    | RErr -> "()"
    | RFd -> "RawFd"
    | RInt -> "c_uint"
    | RInt64 -> "u64"
    | RCookie -> "Cookie"
    | RSizeT -> "usize"
    | RString -> "Vec<u8>"
    | RUInt -> "c_uint"
    | RUIntPtr -> "usize"
    | RUInt64 -> "u64"
    | REnum { enum_prefix = name } | RFlags { flag_prefix = name } ->
        camel_case name
  in
  if call.may_set_error then sprintf "Result<%s>" core_type else core_type

(* Given an argument ([arg : arg]), print Rust code for variable declarations
   for all FFI arguments corresponding to [arg]. That is, for each
   `<FFI_NAME>` in [ffi_arg_names arg], print `let <FFI_NAME> = <...>;`.
   Assuming that a variable with name [rust_arg_name arg] and type
   [rust_arg_type arg] exists in scope. *)
let rust_arg_to_ffi arg =
  let rust_name = rust_arg_name arg in
  let ffi_names = ffi_arg_names arg in
  match arg with
  | Bool _ | Int _ | UInt _ | UIntPtr _ | UInt32 _ | Int64 _ | UInt64 _
  | SizeT _ ->
      let ffi_name = match ffi_names with [ x ] -> x | _ -> assert false in
      pr "let %s = %s;\n" ffi_name rust_name
  | Enum _ ->
      let ffi_name = match ffi_names with [ x ] -> x | _ -> assert false in
      pr "let %s = %s as c_int;\n" ffi_name rust_name
  | Flags _ ->
      let ffi_name = match ffi_names with [ x ] -> x | _ -> assert false in
      pr "let %s = %s.bits();\n" ffi_name rust_name
  | SockAddrAndLen _ ->
      let ffi_addr_name, ffi_len_name =
        match ffi_names with [ x; y ] -> (x, y) | _ -> assert false
      in
      pr "let %s_os = OsSocketAddr::from(%s);\n" rust_name rust_name;
      pr "let %s = %s_os.as_ptr();\n" ffi_addr_name rust_name;
      pr "let %s = %s_os.len();\n" ffi_len_name rust_name
  | String _ ->
      let ffi_name = match ffi_names with [ x ] -> x | _ -> assert false in
      pr
        "let %s_buf = CString::new(%s.into()).map_err(|e| Error::from(e))?;\n"
        rust_name rust_name;
      pr "let %s = %s_buf.as_ptr();\n" ffi_name rust_name
  | Path _ ->
      let ffi_name = match ffi_names with [ x ] -> x | _ -> assert false in
      pr "let %s_buf = " rust_name;
      pr "CString::new(%s.into().into_os_string().into_vec())" rust_name;
      pr ".map_err(|e| Error::from(e))?;\n";
      pr "let %s = %s_buf.as_ptr();\n" ffi_name rust_name
  | StringList _ ->
      let ffi_name = match ffi_names with [ x ] -> x | _ -> assert false in
      (* Create a `Vec` with the arguments as `CString`s. This will copy every
         string and thereby require some extra heap allocations. *)
      pr "let %s_c_strs: Vec<CString> = " ffi_name;
      pr "%s.into_iter()" rust_name;
      pr ".map(|x| CString::new(x.as_ref())";
      pr ".map_err(|e| Error::from(e.to_string())))";
      pr ".collect::<Result<Vec<CString>>>()?;\n";
      (* Create a vector of pointers to all of these `CString`s. For some
         reason, the C API hasn't marked the pointers as const, so we use
         `cast_mut` and `as_mut_ptr` here even though the strings shouldn't be
         modified. *)
      pr "let mut %s_ptrs: Vec<*mut c_char> = \n" ffi_name;
      pr "  %s_c_strs.iter().map(|x| x.as_ptr().cast_mut()).collect();\n"
        ffi_name;
      (* Add a null pointer to mark the end of the list. *)
      pr "%s_ptrs.push(ptr::null_mut());\n" ffi_name;
      pr "let %s = %s_ptrs.as_mut_ptr();\n" ffi_name ffi_name
  | BytesIn _ | BytesPersistIn _ ->
      let ffi_buf_name, ffi_len_name =
        match ffi_names with [ x; y ] -> (x, y) | _ -> assert false
      in
      pr "let %s = %s.as_ptr() as *const c_void;\n" ffi_buf_name rust_name;
      pr "let %s = %s.len();\n" ffi_len_name rust_name
  | BytesOut _ | BytesPersistOut _ ->
      let ffi_buf_name, ffi_len_name =
        match ffi_names with [ x; y ] -> (x, y) | _ -> assert false
      in
      pr "let %s = %s.as_mut_ptr() as *mut c_void;\n" ffi_buf_name rust_name;
      pr "let %s = %s.len();\n" ffi_len_name rust_name
  | Fd _ ->
      let ffi_name = match ffi_names with [ x ] -> x | _ -> assert false in
      pr "let %s = %s.as_raw_fd();\n" ffi_name rust_name
  | Closure _ ->
      let ffi_name = match ffi_names with [ x ] -> x | _ -> assert false in
      pr "let %s = unsafe { crate::bindings::%s_to_raw(%s) };\n" ffi_name
        rust_name rust_name
  | Extent64 _ -> assert false (* only used in extent64_closure *)

(* Same as [rust_arg_to_ffi] but for optional arguments. *)
let rust_optarg_to_ffi arg =
  let rust_name = rust_optarg_name arg in
  let ffi_name = ffi_optarg_name arg in
  match arg with
  | OClosure { cbname } ->
      pr "let %s = match %s {\n" ffi_name rust_name;
      pr "    Some(f) => unsafe { crate::bindings::%s_to_raw(f) },\n"
        rust_name;
      pr "    None => sys::nbd_%s_callback { " cbname;
      pr "callback: None, ";
      pr "free: None, ";
      pr "user_data: ptr::null_mut() ";
      pr "},\n";
      pr "};\n"
  | OFlags (_, { flag_prefix }, _) ->
      let flags_type = camel_case flag_prefix in
      pr "let %s = %s.unwrap_or(%s::empty()).bits();\n" ffi_name rust_name
        flags_type

(* Given a closure argument ([x : cbarg]), print Rust code to create a
   variable with name [rust_cbarg_name x] of type [rust_cbarg_type x].
   Assuming that variables with names from [ffi_cbarg_names x] exists in
   scope. *)
let ffi_cbargs_to_rust cbarg =
  let ffi_names = ffi_cbarg_names cbarg in
  pr "let %s: %s = " (rust_cbarg_name cbarg) (rust_cbarg_type cbarg);
  (match (cbarg, ffi_names) with
  | (CBInt _ | CBUInt _ | CBInt64 _ | CBUInt64 _), [ ffi_name ] ->
      pr "%s" ffi_name
  | CBString _, [ ffi_name ] -> pr "CStr::from_ptr(%s).to_bytes()" ffi_name
  | CBBytesIn _, [ ffi_buf_name; ffi_len_name ] ->
      pr "slice::from_raw_parts(%s as *const u8, %s)" ffi_buf_name
        ffi_len_name
  | CBArrayAndLen (UInt32 _, _), [ ffi_arr_name; ffi_len_name ] ->
      pr "slice::from_raw_parts(%s, %s)" ffi_arr_name ffi_len_name
  | CBArrayAndLen (Extent64 _, _), [ ffi_arr_name; ffi_len_name ] ->
      pr "slice::from_raw_parts(%s as *const NbdExtent, %s)"
        ffi_arr_name ffi_len_name
  | CBArrayAndLen _, [ _; _ ] ->
      failwith
        "generator/Rust.ml: in ffi_cbargs_to_rust: Unsupported type of array \
         element."
  | CBMutable (Int _), [ ffi_name ] -> pr "%s.as_mut().unwrap()" ffi_name
  | CBMutable _, [ _ ] ->
      failwith
        "generator/Rust.ml: in ffi_cbargs_to_rust: Unsupported type of \
         mutable argument."
  | _, _ ->
      failwith
        "generator/Rust.ml: In ffi_cbargs_to_rust: bad number of ffi \
         arguments.");
  pr ";\n"

(* Print Rust code for converting a return value from an FFI call to a Rusty
   return value. In other words, given [x : ret], this functions print a Rust
   expression with type [rust_ret_type x], with a free variable [ffi_ret] with
   the return value from the FFI call. *)
let ffi_ret_to_rust call =
  let ret_type = rust_ret_type call in
  let pure_expr =
    match call.ret with
    | RBool -> "ffi_ret != 0"
    | RErr -> "()"
    | RInt -> "TryInto::<u32>::try_into(ffi_ret).unwrap()"
    | RInt64 -> "TryInto::<u64>::try_into(ffi_ret).unwrap()"
    | RSizeT -> "TryInto::<usize>::try_into(ffi_ret).unwrap()"
    | RCookie -> "Cookie(ffi_ret.try_into().unwrap())"
    | RFd -> "ffi_ret as RawFd"
    | RStaticString -> "unsafe { CStr::from_ptr(ffi_ret) }.to_bytes()"
    | RString ->
        "{ let res = \n"
        ^ "  unsafe { CStr::from_ptr(ffi_ret) }.to_owned().into_bytes();\n"
        ^ "unsafe { libc::free(ffi_ret.cast()); }\n" ^ "res }"
    | RFlags { flag_prefix } ->
        sprintf "%s::from_bits(ffi_ret).unwrap()" ret_type
    | RUInt | RUIntPtr | RUInt64 -> sprintf "ffi_ret as %s" ret_type
    | REnum _ ->
        (* We know that each enum is represented by an isize, hence this
           transmute is safe. *)
        sprintf "unsafe { mem::transmute::<isize, %s>(ffi_ret as isize) }"
          ret_type
  in
  if call.may_set_error then (
    (match call.ret with
    | RBool | RErr | RInt | RFd | RInt64 | RCookie | RSizeT ->
        pr "if ffi_ret < 0 {\n";
        pr "    Err(unsafe { Error::get_error(self.raw_handle()) })\n";
        pr "}\n"
    | RStaticString | RString ->
        pr "if ffi_ret.is_null() {\n";
        pr "    Err(unsafe { Error::get_error(self.raw_handle()) })\n";
        pr "}\n"
    | RUInt | RUIntPtr | RUInt64 | REnum _ | RFlags _ ->
        failwith "In ffi_ret_to_rust: Return type cannot be an error.");
    pr "else { Ok(%s) }\n" pure_expr)
  else pr "%s\n" pure_expr

(* This function prints a rust function which converts a rust closure to a
   (`repr(C)`) struct containing the function pointer, a `*mut c_void` for the
   closure data, and a free function for the closure data. This struct is what
   will be sent to a C function taking the closure as an argument. In fact,
   the struct itself is generated by rust-bindgen. *)
let print_rust_closure_to_raw_fn { cbname; cbargs } =
  let closure_trait = rust_closure_trait cbargs ~lifetime:None in
  let ffi_cbargs_names = List.flatten (List.map ffi_cbarg_names cbargs) in
  let ffi_cbargs_types = List.flatten (List.map ffi_cbarg_types cbargs) in
  let rust_cbargs_names = List.map rust_cbarg_name cbargs in
  pr "pub(crate) unsafe fn %s_to_raw<F>(f: F) -> sys::nbd_%s_callback\n"
    cbname cbname;
  pr "  where F: %s\n" closure_trait;
  pr "{\n";
  pr
    "    unsafe extern \"C\" fn call_closure<F>(data: *mut c_void, %s) -> \
     c_int\n"
    (String.concat ", "
       (List.map2 (sprintf "%s: %s") ffi_cbargs_names ffi_cbargs_types));
  pr "      where F: %s\n" closure_trait;
  pr "    {\n";
  pr "        let callback_ptr = data as *mut F;\n";
  pr "        let callback = &mut *callback_ptr;\n";
  List.iter ffi_cbargs_to_rust cbargs;
  pr "        callback(%s)\n" (String.concat ", " rust_cbargs_names);
  pr "    }\n";
  pr "    let callback_data = Box::into_raw(Box::new(f));\n";
  pr "    sys::nbd_%s_callback {\n" cbname;
  pr "        callback: Some(call_closure::<F>),\n";
  pr "        user_data: callback_data as *mut _,\n";
  pr "        free: Some(utils::drop_data::<F>),\n";
  pr "    }\n";
  pr "}\n";
  pr "\n"

(* Print the comment for a rust function for a handle call. *)
let rec print_rust_handle_call_comment name call =
  (* Print comments. *)
  if call.shortdesc <> "" then
    pr "/// %s\n"
      (String.concat "\n/// " (String.split_on_char '\n' call.shortdesc));
  if call.longdesc <> "" then (
    (* If a short comment was printed, print a blank comment line before
       the long description. *)
    if call.shortdesc <> "" then pr "/// \n";
    let md = longdesc_to_markdown name call.longdesc in
    List.iter (pr "/// %s\n") md
  )

(* Convert POD to rustdoc markdown. *)
and longdesc_to_markdown name longdesc =
  let content = replace_pod_expr name longdesc in

  (* Split input into lines for rest of the processing. *)
  let lines = nsplit "\n" content in

  (* Surround any group of lines starting with whitespace with ```text *)
  let lines =
    List.map (fun line -> string_starts_with ~prefix:" " line, line) lines in
  let (lines : (bool * string list) list) = group_by lines in
  let lines =
    List.map (function
      | true (* verbatim *), lines -> [ "```text" ] @ lines @ [ "```" ]
      | false, lines -> lines
    ) lines in
  let lines = List.flatten lines in

  (* Replace any = directives *)
  filter_map (
    fun s ->
      (* This is a very approximate way to translate bullet lists. *)
      if string_starts_with ~prefix:"=over" s ||
         string_starts_with ~prefix:"=back" s then
        None
      else if string_starts_with ~prefix:"=item" s then (
        let len = String.length s in
        let s' = String.sub s 5 (len-5) in
        Some ("-" ^ s')
      )
      else if string_starts_with ~prefix:"=head" s then (
        let i = int_of_string (String.make 1 s.[5]) in
        let len = String.length s in
        let s' = String.sub s 6 (len-6) in
        Some (String.make i '#' ^ s')
      )
      else if string_starts_with ~prefix:"=" s then
        failwithf "rust: API documentation for %s contains '%s' which
                   cannot be converted to Rust markdown" name s
      else
        Some s
  ) lines

(* Replace any POD X<> expressions.
 * JWZ's rule applies here so we cannot use regexps to parse this.
 *)
and replace_pod_expr name s =
  (* Split string s into the part before "X<", the operator 'X', and
   * the remainder of the string.
   *)
  let before, op, after =
    try
      let i = Str.search_forward (Str.regexp {|[A-Z]<|}) s 0 in
      let op = Some s.[i] in
      let before = String.sub s 0 i in
      let after = String.sub s (i+2) (String.length s - i - 2) in
      before, op, after
    with Not_found -> s, None, "" in

  match op with
  | None -> before
  | Some op ->
     (* Find the content inside the X<...> operator. *)
     let content, rest =
       let n = String.length after in
       let rec loop i depth =
         if i > n then
           failwithf "rust: API documentation for %s contains unclosed %c<...>"
             name op;
         let c = after.[i] in
         match c, depth with
         | '<', _ -> loop (i+1) (depth+1)
         | '>', 0 -> i
         | '>', _ -> loop (i+1) (depth-1)
         | _ -> loop (i+1) depth
       in
       let i = loop 0 0 in
       String.sub after 0 i, String.sub after (i+1) (n-i-1) in

     (* Process the operator. *)
     let new_content =
       let content = replace_pod_expr name content in
       match op with
       | 'C' -> sprintf "`%s`" content (* C<...> becomes `...` *)
       | 'B' -> sprintf "<b>%s</b>" content
       | 'I' | 'F' -> sprintf "<i>%s</i>" content
       | 'E' -> sprintf "&%s;" content
       | 'S' -> (* non-breaking spaces *)
          Str.global_replace (Str.regexp {| \|\t|}) "&nbsp;" content
       | 'L' ->
          let len = String.length content in
          if string_starts_with ~prefix:"nbd_" content then (
            let n = String.sub content 4 (len - 7) in
            if n <> "get_error" && n <> "get_errno" && n <> "close" then
              sprintf "[%s](Handle::%s)" n n
            else
              sprintf "`%s`" n
          )
          else if string_starts_with ~prefix:"http://" content ||
                    string_starts_with ~prefix:"https://" content then
            sprintf "[%s](%s)" content content
          else if String.contains content '|' then (
            let text, link = split "|" content in
            sprintf "[%s](%s)" text link
          )
          else (* external manual page - how to link XXX *)
            sprintf "<i>%s</i>" content
       | _ ->
          failwithf "rust: API documentation for %s contains '%c<...>' which
                     cannot be converted to Rust markdown" name op in

     (* Assemble the output. *)
     before ^ new_content ^ replace_pod_expr name rest

(* Print a Rust expression which converts Rust like arguments to FFI like
   arguments, makes a call on the raw FFI handle, and converts the return
   value to a Rusty type. The expression assumes that variables with name
   `rust_arg_name arg` for all `arg` in `call.args` exists in scope. *)
let print_ffi_call name handle call =
  let ffi_args_names =
    List.flatten (List.map ffi_arg_names call.args)
    @ List.map ffi_optarg_name call.optargs
  in
  pr "{\n";
  pr "    // Convert all arguments to FFI-like types.\n";
  List.iter rust_arg_to_ffi call.args;
  List.iter rust_optarg_to_ffi call.optargs;
  pr "\n";
  pr "    // Call the FFI-function.\n";
  pr "    let ffi_ret = unsafe { sys::nbd_%s(%s, %s) };\n" name handle
    (String.concat ", " ffi_args_names);
  pr "\n";
  pr "    // Convert the result to something more rusty.\n";
  ffi_ret_to_rust call;
  pr "}\n"

(* Print the Rust function for a handle call. Note that this is a "method" on
   the `Handle` struct. So the printed Rust function should be in an `impl
   Handle {` block. *)
let print_rust_handle_method (name, call) =
  let rust_args_names =
    List.map rust_arg_name call.args @ List.map rust_optarg_name call.optargs
  and rust_args_types =
    List.map rust_arg_type call.args @ List.map rust_optarg_type call.optargs
  in
  let rust_args =
    String.concat ", "
      (List.map2 (sprintf "%s: %s") rust_args_names rust_args_types)
  in
  print_rust_handle_call_comment name call;
  (* Print visibility modifier. *)
  if NameSet.mem name hidden_handle_calls then (
    (* If this is hidden to the public API, it might be used only if some feature
     * is active, and we don't want a unused-warning. *)
    pr "#[allow(unused)]\n";
    pr "pub(crate) ")
  else pr "pub ";
  pr "fn %s(&self, %s) -> %s\n" name rust_args (rust_ret_type call);
  print_ffi_call name "self.handle" call;
  pr "\n"

let print_rust_imports () =
  pr "use bitflags::bitflags;\n";
  pr "use crate::{*, types::*};\n";
  pr "use os_socketaddr::OsSocketAddr;\n";
  pr "use std::ffi::*;\n";
  pr "use std::mem;\n";
  pr "use std::net::SocketAddr;\n";
  pr "use std::os::fd::{AsRawFd, OwnedFd, RawFd};\n";
  pr "use std::os::unix::prelude::*;\n";
  pr "use std::path::PathBuf;\n";
  pr "use std::ptr;\n";
  pr "use std::slice;\n";
  pr "use libnbd_sys::nbd_extent;\n";
  pr "\n"

let generate_rust_bindings () =
  generate_header CStyle ~copyright:"Tage Johansson";
  pr "\n";
  print_rust_imports ();
  List.iter print_rust_constant constants;
  pr "\n";
  List.iter print_rust_enum all_enums;
  List.iter print_rust_flags all_flags;
  List.iter print_metadata_namespace metadata_namespaces;
  List.iter print_rust_closure_to_raw_fn all_closures;
  pr "impl Handle {\n";
  List.iter print_rust_handle_method handle_calls;
  pr "}\n\n"

(*********************************************************)
(* The rest of the file concerns the asynchronous API.   *)
(*                                                       *)
(* See the comments in rust/src/async_handle.rs for more *)
(* information about how it works.                       *)
(*********************************************************)

let excluded_handle_calls : NameSet.t =
  NameSet.of_list
  @@ [
       "aio_get_fd";
       "aio_get_direction";
       "clear_debug_callback";
       "get_debug";
       "set_debug";
       "set_debug_callback";
     ]
  @ (handle_calls
    |> List.filter (fun (_, { modifies_fd }) -> modifies_fd)
    |> List.map (fun (name, _) -> name))

(* A mapping with names as keys. *)
module NameMap = Map.Make (String)

(* Strip "aio_" from the beginning of a string. *)
let strip_aio name : string =
  if string_starts_with ~prefix:"aio_" name then
    String.sub name 4 (String.length name - 4)
  else failwithf "Asynchronous call %s must begin with aio_" name

(* A map with all asynchronous handle calls. The keys are names with "aio_"
   stripped, the values are a tuple with the actual name (with "aio_"), the
   [call] and the [async_kind]. *)
let async_handle_calls : (string * call * async_kind) NameMap.t =
  handle_calls
  |> List.filter (fun (n, _) -> not (NameSet.mem n excluded_handle_calls))
  |> filter_map (fun (name, call) ->
         call.async_kind
         |> option_map (fun async_kind ->
                (strip_aio name, (name, call, async_kind))))
  |> List.fold_left (fun m (k, v) -> NameMap.add k v m) NameMap.empty

(* A mapping with all synchronous (not asynchronous) handle calls. Excluded
   are also all synchronous calls that have an asynchronous counterpart. So if
   "foo" is the name of a handle call and an asynchronous call "aio_foo"
   exists, then "foo" will not be in this map. *)
let sync_handle_calls : call NameMap.t =
  handle_calls
  |> List.filter (fun (n, _) -> not (NameSet.mem n excluded_handle_calls))
  |> List.filter (fun (n, _) -> not (NameMap.mem n async_handle_calls))
  |> List.fold_left (fun m (k, v) -> NameMap.add k v m) NameMap.empty

(* Get the Rust type for an argument in the asynchronous API. Like
   [rust_arg_type] but no static lifetime on some buffers. *)
let rust_async_arg_type : arg -> string = function
  | BytesPersistIn _ -> "&[u8]"
  | BytesPersistOut _ -> "&mut [u8]"
  | x -> rust_arg_type x

(* Get the Rust type for an optional argument in the asynchronous API. Like
   [rust_optarg_type] but no static lifetime on some closures. *)
let rust_async_optarg_type : optarg -> string = function
  | OClosure x -> sprintf "Option<%s>" (rust_async_arg_type (Closure x))
  | x -> rust_optarg_type x

(* A string of the argument list for a method on the handle, with both
   mandatory and optional arguments. *)
let rust_async_handle_call_args { args; optargs } : string =
  let rust_args_names =
    List.map rust_arg_name args @ List.map rust_optarg_name optargs
  and rust_args_types =
    List.map rust_async_arg_type args
    @ List.map rust_async_optarg_type optargs
  in
  String.concat ", "
    (List.map2 (sprintf "%s: %s") rust_args_names rust_args_types)

(* Print the Rust function for a synchronous handle call. *)
let print_rust_sync_handle_call name call =
  print_rust_handle_call_comment name call;
  pr "pub fn %s(&self, %s) -> %s\n" name
    (rust_async_handle_call_args call)
    (rust_ret_type call);
  print_ffi_call name "self.data.handle.handle" call;
  pr "\n"

(* Print the Rust function for an asynchronous handle call with a completion
   callback. (Note that "callback" might be abbreviated with "cb" in the
   following code. *)
let print_rust_async_handle_call_with_completion_cb name aio_name call =
  (* An array of all optional arguments. Useful because we need to deal with
     the index of the completion callback. *)
  let optargs = Array.of_list call.optargs in
  (* The index of the completion callback in [optargs] *)
  let completion_cb_index =
    array_find_map
      (fun (i, optarg) ->
        match optarg with
        | OClosure { cbname } ->
            if cbname = "completion" then Some i else None
        | _ -> None)
      (Array.mapi (fun x y -> (x, y)) optargs)
  in
  let completion_cb_index =
    match completion_cb_index with
    | Some x -> x
    | None ->
        failwithf
          "The handle call %s is claimed to have a completion callback among \
           its optional arguments by the async_kind field, but that does not \
           seem to be the case."
          aio_name
  in
  let optargs_before_completion_cb =
    Array.to_list (Array.sub optargs 0 completion_cb_index)
  and optargs_after_completion_cb =
    Array.to_list
      (Array.sub optargs (completion_cb_index + 1)
         (Array.length optargs - (completion_cb_index + 1)))
  in
  (* All optional arguments excluding the completion callback. *)
  let optargs_without_completion_cb =
    optargs_before_completion_cb @ optargs_after_completion_cb
  in
  print_rust_handle_call_comment name call;
  pr "pub async fn %s(&self, %s) -> SharedResult<()> {\n" name
    (rust_async_handle_call_args
       { call with optargs = optargs_without_completion_cb });
  pr "    // A oneshot channel to notify when the call is completed.\n";
  pr "    let (ret_tx, ret_rx) = oneshot::channel::<SharedResult<()>>();\n";
  pr "    let (ccb_tx, mut ccb_rx) = oneshot::channel::<c_int>();\n";
  (* Completion callback: *)
  pr "    let %s = Some(utils::fn_once_to_fn_mut(|err: &mut i32| {\n"
    (rust_optarg_name (Array.get optargs completion_cb_index));
  pr "      ccb_tx.send(*err).ok();\n";
  pr "      1\n";
  pr "    }));\n";
  (* End of completion callback. *)
  print_ffi_call aio_name "self.data.handle.handle" call;
  pr "?;\n";
  pr "    let mut ret_tx = Some(ret_tx);\n";
  pr "    let completion_predicate = \n";
  pr "     move |_handle: &Handle, res: &SharedResult<()>| {\n";
  pr "      let ret = match res {\n";
  pr "        Err(e) if e.is_fatal() => res.clone(),\n";
  pr "        _ => {\n";
  pr "          let Ok(errno) = ccb_rx.try_recv() else { return false; };\n";
  pr "          if errno == 0 {\n";
  pr "            Ok(())\n";
  pr "          } else {\n";
  pr "            if let Err(e) = res {\n";
  pr "              Err(e.clone())\n";
  pr "            } else {\n";
  pr "              Err(Arc::new(";
  pr "                Error::Recoverable(ErrorKind::from_errno(errno))))\n";
  pr "            }\n";
  pr "          }\n";
  pr "        },\n";
  pr "      };\n";
  pr "      ret_tx.take().unwrap().send(ret).ok();\n";
  pr "      true\n";
  pr "    };\n";
  pr "    self.add_command(completion_predicate)?;\n";
  pr "    ret_rx.await.unwrap()\n";
  pr "}\n\n"

(* Print a Rust function for an asynchronous handle call which signals
   completion by changing state. The predicate is a call like
   "aio_is_connecting" which should get the value (like false) for the call to
   be complete. *)
let print_rust_async_handle_call_changing_state name aio_name call
    (predicate, value) =
  let value = if value then "true" else "false" in
  print_rust_handle_call_comment name call;
  pr "pub async fn %s(&self, %s) -> SharedResult<()>\n" name
    (rust_async_handle_call_args call);
  pr "{\n";
  print_ffi_call aio_name "self.data.handle.handle" call;
  pr "?;\n";
  pr "    let (ret_tx, ret_rx) = oneshot::channel::<SharedResult<()>>();\n";
  pr "    let mut ret_tx = Some(ret_tx);\n";
  pr "    let completion_predicate = \n";
  pr "     move |handle: &Handle, res: &SharedResult<()>| {\n";
  pr "      let ret = if let Err(_) = res {\n";
  pr "        res.clone()\n";
  pr "      } else {\n";
  pr "        if handle.%s() != %s { return false; }\n" predicate value;
  pr "        else { Ok(()) }\n";
  pr "      };\n";
  pr "      ret_tx.take().unwrap().send(ret).ok();\n";
  pr "      true\n";
  pr "    };\n";
  pr "    self.add_command(completion_predicate)?;\n";
  pr "    ret_rx.await.unwrap()\n";
  pr "}\n\n"

(* Print an impl with all handle calls. *)
let print_rust_async_handle_impls () =
  pr "impl AsyncHandle {\n";
  NameMap.iter print_rust_sync_handle_call sync_handle_calls;
  async_handle_calls
  |> NameMap.iter (fun name (aio_name, call, async_kind) ->
         match async_kind with
         | WithCompletionCallback ->
             print_rust_async_handle_call_with_completion_cb name aio_name
               call
         | ChangesState (predicate, value) ->
             print_rust_async_handle_call_changing_state name aio_name call
               (predicate, value));
  pr "}\n\n"

let print_rust_async_imports () =
  pr "use crate::{*, types::*};\n";
  pr "use os_socketaddr::OsSocketAddr;\n";
  pr "use std::ffi::*;\n";
  pr "use std::mem;\n";
  pr "use std::net::SocketAddr;\n";
  pr "use std::os::fd::{AsRawFd, OwnedFd};\n";
  pr "use std::os::unix::prelude::*;\n";
  pr "use std::path::PathBuf;\n";
  pr "use std::ptr;\n";
  pr "use std::sync::Arc;\n";
  pr "use tokio::sync::oneshot;\n";
  pr "\n"

let generate_rust_async_bindings () =
  generate_header CStyle ~copyright:"Tage Johansson";
  pr "\n";
  print_rust_async_imports ();
  print_rust_async_handle_impls ()
