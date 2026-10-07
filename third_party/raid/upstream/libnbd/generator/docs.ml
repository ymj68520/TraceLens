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

open Printf

open API
open Utils

(* We generate a fragment of Makefile.am containing the list
 * of generated functions, used in rules for building the manual
 * pages.  We exploit GNU make's sinclude to use this file without
 * upsetting automake.
 *)
let generate_docs_Makefile_inc () =
  generate_header HashStyle;

  pr "api_built += \\\n";
  List.iter (
    fun (name, _) ->
      pr "\tnbd_%s \\\n" name;
  ) handle_calls;
  pr "\t$(NULL)\n"

let generate_docs_api_links_pod () =
  let pages =
    List.map (fun (name, _) -> sprintf "nbd_%s(3)" name) handle_calls in
  let pages =
    "nbd_create(3)" ::
    "nbd_close(3)" ::
    "nbd_get_error(3)" ::
    "nbd_get_errno(3)" ::
    pages in
  let pages = List.sort compare pages in

  List.iteri (
    fun i page ->
      if i > 0 then pr ",\n";
      pr "L<%s>" page
  ) pages;
  pr ".\n"

let generate_docs_api_flag_links_pod () =
  let pages =
    filter_map (
      fun (name, _) ->
        if (is_prefix name "is_" && name <> "is_uri") ||
             is_prefix name "can_" then
          Some (sprintf "nbd_%s(3)" name)
        else
          None
    ) handle_calls in
  let pages = List.sort compare pages in

  List.iteri (
    fun i page ->
      if i > 0 then pr ",\n";
      pr "L<%s>" page
  ) pages;
  pr ".\n"

let print_docs_closure { cbname; cbargs } =
  pr " typedef struct {\n";
  pr "   int (*callback) ";
  C.print_cbarg_list ~wrap:true ~maxcol:60 cbargs;
  pr ";\n";
  pr "   void *user_data;\n";
  pr "   void (*free) (void *user_data);\n";
  pr " } nbd_%s_callback;\n" cbname

let generate_docs_nbd_pod name { args; optargs; ret;
                                 shortdesc; longdesc; notes;
                                 example; see_also;
                                 permitted_states; may_set_error;
                                 first_version = (major, minor) } () =
  pr "=head1 NAME\n";
  pr "\n";
  pr "nbd_%s -" name;
  (* Don't use pr_wrap here because it leaves trailing whitespace. *)
  let words = nsplit " " shortdesc in
  List.iter (
    fun word ->
      if output_column () + String.length word > 70 then pr "\n%s" word
      else pr " %s" word
  ) words;
  pr "\n";
  pr "\n";

  pr "=head1 SYNOPSIS\n";
  pr "\n";
  pr " #include <libnbd.h>\n";
  pr "\n";

  List.iter (
    function
    | Closure cb -> print_docs_closure cb; pr "\n"
    | _ -> ()
  ) args;
  List.iter (
    function
    | OClosure cb -> print_docs_closure cb; pr "\n"
    | _ -> ()
  ) optargs;

  pr " ";
  C.print_call ~wrap:true ~maxcol:60 name args optargs ret;
  pr ";\n";
  pr "\n";

  pr "=head1 DESCRIPTION\n";
  pr "\n";
  pr "%s\n" longdesc;
  pr "\n";

  pr "=head1 RETURN VALUE\n";
  pr "\n";
  let errcode = C.errcode_of_ret ret in
  (match ret with
   | RBool ->
      pr "This call returns a boolean value.\n"
   | RStaticString ->
      pr "This call returns a statically allocated string, valid for the\n";
      pr "lifetime of the process or until libnbd is unloaded by\n";
      pr "L<dlclose(3)>.  You B<must not> try to free the string.\n"
   | RErr ->
      pr "If the call is successful the function returns C<0>.\n"
   | RFd ->
      pr "This call returns a file descriptor.\n"
   | RInt ->
      pr "This call returns an integer E<ge> C<0>.\n";
   | RInt64 ->
      pr "This call returns a 64 bit signed integer E<ge> C<0>.\n";
   | RCookie ->
      pr "This call returns the 64 bit cookie of the command.\n";
      pr "The cookie is E<ge> C<1>.\n";
      pr "Cookies are unique (per libnbd handle, not globally).\n"
   | RSizeT ->
      pr "This call returns an integer size E<ge> C<0>.\n";
   | RString ->
      pr "This call returns a string.  The caller must free the\n";
      pr "returned string to avoid a memory leak.\n";
   | RUInt ->
      pr "This call returns a bitmask.\n";
   | RUIntPtr ->
      pr "This call returns a C<uintptr_t>.\n";
   | RUInt64 ->
      pr "This call returns a counter.\n";
   | REnum { enum_prefix } ->
      pr "This call returns one of the LIBNBD_%s_* values.\n" enum_prefix;
   | RFlags { flag_prefix } ->
      pr "This call returns a bitmask of LIBNBD_%s_* values.\n" flag_prefix;
  );
  pr "\n";

  pr "=head1 ERRORS\n";
  pr "\n";

  if may_set_error then (
    let value = match errcode with
      | Some value -> value
      | None -> assert false in
    pr "On error C<%s> is returned.\n" value;
    pr "\n";
    pr "Refer to L<libnbd(3)/ERROR HANDLING>\n";
    pr "for how to get further details of the error.\n"
  )
  else
    pr "This function does not fail.\n";
  pr "\n";

  pr "The following parameters must not be NULL: C<h>";
  List.iter (
    fun arg ->
      let nns = C.arg_attr_nonnull arg in
      if List.mem true nns then pr ", C<%s>" (List.hd (C.name_of_arg arg))
  ) args;
  List.iter (
    fun arg ->
      let nns = C.optarg_attr_nonnull arg in
      if List.mem true nns then pr ", C<%s>" (C.name_of_optarg arg)
  ) optargs;
  pr ".\n";
  pr "For more information see L<libnbd(3)/Non-NULL parameters>.\n";
  pr "\n";

  let notes_links = ref [] in
  if notes <> [] then (
    pr "=head1 NOTES\n";
    pr "\n";
    List.iter (
      fun note ->
        let note =
          match note with
          | BlockingConnectCall -> blocking_connect_call_description
          | AsyncConnectCall ->    async_connect_call_description
          | StrictCall ->          strict_call_description
          | NonBlockingCall ->     non_blocking_call_description in
        notes_links := !notes_links @ extract_links note;
        pr "%s\n" note
    ) notes;
    pr "\n";
  );

  if permitted_states <> [] then (
    pr "=head1 HANDLE STATE\n";
    pr "\n";
    pr "nbd_%s\ncan be called when the handle is in the following %s:\n"
      name (if List.length permitted_states = 1 then "state" else "states");
    pr "\n";
    pr " ┌─────────────────────────────────────┬─────────────────────────┐\n";
    let row ps description =
      let permitted = List.mem ps permitted_states in
      pr " │ %-35s │ %s %-20s │\n" description
        (if permitted then "✅" else "❌")
        (if permitted then "allowed" else "error")
    in
    List.iter (
      fun ps ->
      match ps with
      | Created ->     row ps "Handle created, before connecting"
      | Connecting ->  row ps "Connecting"
      | Negotiating -> row ps "Connecting & handshaking (opt_mode)"
      | Connected ->   row ps "Connected to the server"
      | Closed ->      row ps "Connection shut down"
      | Dead ->        row ps "Handle dead"
    ) all_permitted_states;
    pr " └─────────────────────────────────────┴─────────────────────────┘\n";
    pr "\n"
  );

  pr "=head1 VERSION\n";
  pr "\n";
  pr "This function first appeared in libnbd %d.%d.\n" major minor;
  pr "\n";
  pr "If you need to test if this function is available at compile time\n";
  pr "check if the following macro is defined:\n";
  pr "\n";
  pr " #define LIBNBD_HAVE_NBD_%s 1\n" (String.uppercase_ascii name);
  pr "\n";

  (match example with
   | None -> ()
   | Some filename ->
      pr "=head1 EXAMPLE\n";
      pr "\n";
      pr "This example is also available as F<%s>\n" filename;
      pr "in the libnbd source code.\n";
      pr "\n";
      let chan = open_in filename in
      (try
         while true do
           let line = input_line chan in
           let len = String.length line in
           if len > 60 then
             failwithf "%s: %s: line too long in example" name filename;
           if len = 0 then pr "\n" else pr " %s\n" line
         done
       with End_of_file -> ()
      );
      close_in chan;
      pr "\n"
  );

  let () =
    pr "=head1 SEE ALSO\n";
    pr "\n";
    let other_links = extract_links longdesc in
    let std_links = [MainPageLink; Link "create"] in
    let links = see_also @ other_links @ std_links @ !notes_links in
    let links = sort_uniq_links links in
    List.iter verify_link links;
    let links = List.map pod_of_link links in
    let comma = ref false in
    List.iter (
      fun pod ->
        if !comma then pr ",\n"; comma := true;
        pr "%s" pod
    ) links;
    pr ".\n\n" in

  pr {|=head1 AUTHORS

Eric Blake

Richard W.M. Jones

=head1 COPYRIGHT

Copyright Red Hat
|}
