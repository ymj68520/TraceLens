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

open Printf
open Unix

type location = string * int
let noloc = ("", 0)

let failwithf fs = ksprintf failwith fs

let rec filter_map f = function
  | [] -> []
  | x :: xs ->
      match f x with
      | Some y -> y :: filter_map f xs
      | None -> filter_map f xs

(* group_by [1, "foo"; 2, "bar"; 2, "baz"; 2, "biz"; 3, "boo"; 4, "fizz"]
 * - : (int * string list) list =
 * [(1, ["foo"]); (2, ["bar"; "baz"; "biz"]); (3, ["boo"]); (4, ["fizz"])]
 *)
let rec group_by = function
| [] -> []
| (day1, x1) :: (day2, x2) :: rest when day1 = day2 ->
   let rest = group_by ((day2, x2) :: rest) in
   let day, xs = List.hd rest in
   (day, x1 :: xs) :: List.tl rest
| (day, x) :: rest ->
   (day, [x]) :: group_by rest

let uniq ?(cmp = compare) xs =
  let rec loop acc = function
    | [] -> acc
    | [x] -> x :: acc
    | x :: (y :: _ as xs) when cmp x y = 0 ->
       loop acc xs
    | x :: (y :: _ as xs) ->
       loop (x :: acc) xs
  in
  List.rev (loop [] xs)

let is_prefix str prefix =
  let n = String.length prefix in
  String.length str >= n && String.sub str 0 n = prefix

let rec find s sub =
  let len = String.length s in
  let sublen = String.length sub in
  let rec loop i =
    if i <= len-sublen then (
      let rec loop2 j =
        if j < sublen then (
          if s.[i+j] = sub.[j] then loop2 (j+1)
          else -1
        ) else
          i (* found *)
      in
      let r = loop2 0 in
      if r = -1 then loop (i+1) else r
    ) else
      -1 (* not found *)
  in
  loop 0

let rec split sep str =
  let len = String.length sep in
  let seplen = String.length str in
  let i = find str sep in
  if i = -1 then str, ""
  else (
    String.sub str 0 i, String.sub str (i + len) (seplen - i - len)
  )

and nsplit sep str =
  if find str sep = -1 then
    [str]
  else (
    let s1, s2 = split sep str in
    s1 :: nsplit sep s2
  )

let char_mem c str = String.contains str c

let span str accept =
  let len = String.length str in
  let rec loop i =
    if i >= len then len
    else if char_mem (String.unsafe_get str i) accept then loop (i+1)
    else i
  in
  loop 0

let cspan str reject =
  let len = String.length str in
  let rec loop i =
    if i >= len then len
    else if char_mem (String.unsafe_get str i) reject then i
    else loop (i+1)
  in
  loop 0

(* String.starts_with was added in OCaml 4.13 so we include this for
 * earlier versions of OCaml.
 *)
let string_starts_with ~prefix s =
  let len_s = String.length s and len_pre = String.length prefix in
  let rec aux i =
    if i = len_pre then true
    else if String.unsafe_get s i <> String.unsafe_get prefix i then false
    else aux (i + 1)
  in
  len_s >= len_pre && aux 0

(* Array.find_map was added in OCaml 4.13 *)
let array_find_map f a =
  let n = Array.length a in
  let rec loop i =
    if i = n then None
    else
      match f (Array.unsafe_get a i) with
      | None -> loop (succ i)
      | Some _ as r -> r
  in
  loop 0

(* Option module was added in OCaml 4.08 *)
let option_map f o = match o with None -> None | Some v -> Some (f v)

(* Current output line and column. *)
let lineno = ref 1 and col = ref 0

type chan = NoOutput | OutChannel of out_channel | Buffer of Buffer.t
let chan = ref NoOutput
let pr fs =
  ksprintf (
    fun str ->
      (* Maintain the current output row & column.  This only
       * works for 7 bit ASCII but that's enough for what we need
       * this for.
       *)
      for i = 0 to String.length str - 1 do
        if String.unsafe_get str i = '\n' then (
          col := 0;
          incr lineno
        ) else
          incr col
      done;
      match !chan with
      | NoOutput -> failwithf "use ‘output_to’ to set output"
      | OutChannel chan -> output_string chan str
      | Buffer b -> Buffer.add_string b str
  ) fs

let spaces n = String.make n ' '

(* Convert s to macro name by changing '-' to '_' and eliding ':'. *)
let macro_name s =
  let underscore = Str.global_replace (Str.regexp_string "-") "_" s in
  Str.global_replace (Str.regexp ":") "" underscore

(* Save the current output channel and replace it with a temporary buffer while
 * running ‘code’.  Return the buffer.
 *)
let pr_buf code =
  let old_chan = !chan in
  let wrapping_col = !col in
  let b = Buffer.create 1024 in
  chan := Buffer b;
  let exn = try code (); None with exn -> Some exn in
  chan := old_chan;
  col := wrapping_col;
  match exn with None -> b | Some exn -> raise exn

(* Wrap the output at maxcol, breaking up lines when a 'c' character
 * occurs.  For example:
 *   foobar = a, b, c, d, e, f, g
 *            └── pr_wrap ',' ──┘
 * becomes:
 *   foobar = a, b, c,
 *            d, e, f,
 *            g
 *)
let pr_wrap ?(maxcol = 76) c code =
  (* Save the current output channel and replace it with a
   * temporary buffer while running ‘code’.  Then we wrap the
   * buffer and write it to the restored channel.
   *)
  let b = pr_buf code in
  let wrapping_col = !col in
  let lines = nsplit "\n" (Buffer.contents b) in
  match lines with
  | [] -> ()
  | line :: rest ->
     let fields = nsplit (String.make 1 c) line in
     let maybe_wrap field =
       (* Note that here we break even if we'd fill ‘maxcol‘ precisely;
        * that's because...
        *)
       if !col > wrapping_col && !col + String.length field >= maxcol then (
         pr "\n%s" (spaces wrapping_col);
         match span field " \t" with
         | 0 -> field
         | i -> String.sub field i (String.length field - i)
       )
       else field
     in
     let rec loop = function
       | [] -> ()
       | f :: [] -> let f = maybe_wrap f in pr "%s" f;
       | f :: fs ->
           let f = maybe_wrap f in
           (* ... here we append the separator. *)
           pr "%s%c" f c;
           loop fs
     in
     loop fields;

     (* There should really only be one line in the buffer, but
      * if there are multiple apply wrapping to only the first one.
      *)
     pr "%s" (String.concat "\n" rest)

(* Wrap the C string literal output at ‘maxcol’, breaking up lines when a space
 * character occurs.  For example:
 *   foobar = "a b c d e f g h i j k"
 *             └── pr_wrap_cstr ───┘
 * becomes:
 *   foobar = "a b c d "
 *            "e f g h "
 *            "i j k"
 *
 * Note that:
 * - ‘code’ MUST NOT produce the surrounding quotes,
 * - ‘code’ MUST NOT produce multiple lines,
 * - ‘code’ MUST do its own quoting,
 * - space characters produced by ‘code’ cannot be escaped from wrapping.
 *)
let pr_wrap_cstr ?(maxcol = 76) code =
  (* Just before entering ‘pr_wrap_cstr’, a leading quote must have been
   * produced.
   *)
  let wrapping_col = !col - 1 in
  assert (wrapping_col >= 0);

  let b = pr_buf code in
  let lines = nsplit "\n" (Buffer.contents b) in
  match lines with
  | [] -> ()
  | line :: [] ->
     let fields = nsplit " " line in
     let nfields = List.length fields in
     let indent = spaces wrapping_col in
     List.iteri
       (fun i field ->
          (* Append a space character to each field except the last. *)
          let f = if i < nfields - 1 then field ^ " " else field in

          (* Terminate the string literal, insert a line break, and start a
           * properly indented new string literal, before printing the field, if
           * (a) the field is not the first one in this string literal, and (b)
           * printing the field plus a literal-terminating quote would not fit
           * in ‘maxcol’.
           *
           * Note that this way, the literal-terminating quote will always fit
           * in ‘maxcol’, except when the *sole* field in the literal is too
           * long.
           *)
          if !col > wrapping_col + 1 &&
             !col + (String.length f) + 1 > maxcol then
            pr "\"\n%s\"" indent;

          (* Print the field. *)
          pr "%s" f
       ) fields
  | _ -> assert false

(* Wrap a string as a (potentially multi-line) C comment. Two things to note:
 * - the function produces both the starting slash-star and the ending
 *   star-slash,
 * - newline characters in the input are not allowed.
 *)
let pr_wrap_c_comment ?(maxcol = 80) code =
  (* The comment delimiters. *)
  let start = "/* "
  and sep   = " * "
  and stop  = " */"

  (* Format the comment into a buffer, and append a space character, for forcing
   * a nonspace -> space transition at the end of the comment, provided the
   * comment ends with a nonspace. Note that trailing spaces will be swallowed
   * anyway, as only nonspace -> space transitions produce output.
   *)
  and comment = pr_buf (fun () -> code (); pr " ")

  (* Capture the current column / indentation. *)
  and indent = spaces !col

  (* Whether we're currently scanning spaces. We start the loop under the
   * assumption "scanning spaces" because a space -> nonspace transition does
   * not try to output anything.
   *)
  and scanning_spaces = ref true

  (* The "buffers" for accumulating spaces and nonspaces. *)
  and spaces_start = ref 0
  and nonspaces_start = ref 0

  (* Whether we've needed to insert at least one line break. *)
  and multiline = ref false in

  pr "%s" start;

  for i = 0 to Buffer.length comment - 1 do
    let ch = Buffer.nth comment i in

    (* Newlines are invalid... *)
    assert (ch <> '\n');

    match !scanning_spaces, ch with
    | true, ' ' ->
        ()
    | true, _ ->
        (* Space -> nonspace transition. *)
        scanning_spaces := false;
        nonspaces_start := i
    | false, ' ' ->
        (* Nonspace -> space transition. If the buffered spaces:
         *
         *   nonspaces_start - spaces_start
         *
         * plus the buffered nonspaces:
         *
         *   i - nonspaces_start
         *
         * fit on the current line, then print both buffers. (Note that the sum
         * of those addends is just (i - spaces_start).)
         *
         * Otherwise, insert a line break and a comment line separator, and only
         * print the nonspaces.
         *)
        if !col + (i - !spaces_start) <= maxcol then
          pr "%s" (Buffer.sub comment !spaces_start (i - !spaces_start))
        else (
          pr "\n%s%s%s" indent sep
            (Buffer.sub comment !nonspaces_start (i - !nonspaces_start));
          multiline := true
        );

        scanning_spaces := true;
        spaces_start := i
    | false, _ ->
        ()
  done;

  (* If the comment has fit on a single line, and we've got room left for the
   * terminator, then place the terminator on the same line. Otherwise, break
   * the terminator to a new line.
   *)
  if not !multiline && !col + String.length stop <= maxcol then
    pr "%s" stop
  else
    pr "\n%s%s" indent stop

let output_lineno () = !lineno
let output_column () = !col

let string_of_location (file, lineno) = sprintf "%s:%d" file lineno
let line_directive_of_location (file, lineno) =
  sprintf "#line %d \"%s\"" lineno file

type comment_style =
  | CStyle | CPlusPlusStyle | HashStyle | OCamlStyle | HaskellStyle
  | PODCommentStyle

let generate_header ?(extra_sources = []) ?(copyright = "Red Hat")
    comment_style =
  let inputs = "generator/generator" :: extra_sources in
  let c = match comment_style with
    | CStyle ->         pr "/* "; " *"
    | CPlusPlusStyle -> pr "// "; "//"
    | HashStyle ->      pr "# ";  "#"
    | OCamlStyle ->     pr "(* "; " *"
    | HaskellStyle ->   pr "{- "; "  "
    | PODCommentStyle -> pr "=begin comment\n\n "; "" in
  pr "NBD client library in userspace\n";
  pr "%s WARNING: THIS FILE IS GENERATED FROM\n" c;
  pr "%s %s\n" c (String.concat " " inputs);
  pr "%s ANY CHANGES YOU MAKE TO THIS FILE WILL BE LOST.\n" c;
  pr "%s\n" c;
  pr "%s Copyright %s\n" c copyright;
  pr "%s\n" c;
  pr "%s This library is free software; you can redistribute it and/or\n" c;
  pr "%s modify it under the terms of the GNU Lesser General Public\n" c;
  pr "%s License as published by the Free Software Foundation; either\n" c;
  pr "%s version 2 of the License, or (at your option) any later version.\n" c;
  pr "%s\n" c;
  pr "%s This library is distributed in the hope that it will be useful,\n" c;
  pr "%s but WITHOUT ANY WARRANTY; without even the implied warranty of\n" c;
  pr "%s MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU\n" c;
  pr "%s Lesser General Public License for more details.\n" c;
  pr "%s\n" c;
  pr "%s You should have received a copy of the GNU Lesser General Public\n" c;
  pr "%s License along with this library; if not, write to the Free Software\n" c;
  pr "%s Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA\n" c;
  (match comment_style with
   | CStyle -> pr " */\n"
   | CPlusPlusStyle
   | HashStyle -> ()
   | OCamlStyle -> pr " *)\n"
   | HaskellStyle -> pr "-}\n"
   | PODCommentStyle -> pr "\n=end comment\n"
  );
  pr "\n"

let quote = Filename.quote

let files_equal n1 n2 =
  let cmd = sprintf "cmp -s %s %s" (quote n1) (quote n2) in
  match Sys.command cmd with
  | 0 -> true
  | 1 -> false
  | i -> failwithf "%s: failed with error code %d" cmd i

type formatter =
  | Gofmt
  | Rustfmt

let output_to ?(formatter = None) filename k =
  lineno := 1; col := 0;
  let filename_new = filename ^ ".new" in
  let c = open_out filename_new in
  chan := OutChannel c;
  k ();
  close_out c;
  chan := NoOutput;
  (match formatter with
  | Some Gofmt ->
     (match Config.gofmt with
      |  Some gofmt ->
          (let cmd = sprintf "%s -w %s" gofmt filename_new in
           match system cmd with
           | WEXITED 0 -> ()
           | WEXITED i -> failwithf "gofmt failed with exit code %d" i
           | WSIGNALED i | WSTOPPED i ->
              failwithf "gofmt was killed or stopped by signal %d" i
          )
      | None -> ()
     )
  | Some Rustfmt ->
     (match Config.rustfmt with
      | Some rustfmt ->
         (let cmd = sprintf "%s %s" rustfmt filename_new in
          match system cmd with
          | WEXITED 0 -> ()
          | WEXITED i -> failwithf "rustfmt failed with exit code %d" i
          | WSIGNALED i | WSTOPPED i ->
             failwithf "rustfmt was killed or stopped by signal %d" i
         )
      | None -> ()
     )
  | None -> ());
  (* Is the new file different from the current file? *)
  if Sys.file_exists filename && files_equal filename filename_new then
    unlink filename_new                 (* same, so skip it *)
  else (
    (* different, overwrite old one *)
    (try chmod filename 0o644 with Unix_error _ -> ());
    rename filename_new filename;
    chmod filename 0o444;
    printf "written %s\n%!" filename;
  )

(* Convert POD fragments into plain text.
 *
 * For man pages and Perl documentation we can simply use the POD
 * directly, and that is the best solution.  However for other
 * programming languages we have to convert the POD fragments to
 * plain text by running it through pod2text.
 *
 * The problem is that pod2text is very slow so we must cache
 * the converted fragments to disk.
 *
 * Increment the version in the filename whenever the cache
 * type changes.
 *)

type cache_key = string (* longdesc *)
type cache_value = string list (* list of plain text lines *)

let (cache : (cache_key, cache_value) Hashtbl.t), save_cache =
  let cachefile = "generator/generator-cache.v1" in
  let cache =
    try
      let chan = open_in cachefile in
      let ret = input_value chan in
      close_in chan;
      ret
    with _ ->
      printf "Regenerating the cache, this could take a little while ...\n%!";
      Hashtbl.create 13 in
  let save_cache () =
    let chan = open_out cachefile in
    output_value chan cache;
    close_out chan
  in
  cache, save_cache

let pod2text longdesc =
  let key : cache_key = longdesc in
  try Hashtbl.find cache key
  with Not_found ->
    let filename, chan = Filename.open_temp_file "pod2text" ".tmp" in
    fprintf chan "=encoding utf8\n\n";
    fprintf chan "=head1 NAME\n\n%s\n" longdesc;
    close_out chan;
    let cmd = sprintf "pod2text -w 60 %s" (quote filename) in
    let chan = open_process_in cmd in
    let lines = ref [] in
    let rec loop i =
      let line = input_line chan in
      if i = 1 then (* discard first line of output *)
        loop (i+1)
      else (
        lines := line :: !lines;
        loop (i+1)
      ) in
    let lines : cache_value =
      try loop 1 with End_of_file -> List.rev !lines in
    unlink filename;
    (match close_process_in chan with
     | WEXITED 0 -> ()
     | WEXITED i ->
        failwithf "pod2text: process exited with non-zero status (%d)" i
     | WSIGNALED i | WSTOPPED i ->
        failwithf "pod2text: process signalled or stopped by signal %d" i
    );
    Hashtbl.add cache key lines;
    save_cache ();
    lines

let camel_case name =
  let xs = nsplit "_" name in
  List.fold_left (
    fun a x ->
      a ^ String.uppercase_ascii (Str.first_chars x 1) ^
          String.lowercase_ascii (Str.string_after x 1)
  ) "" xs
