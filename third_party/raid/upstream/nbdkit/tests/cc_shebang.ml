(*/.)>/dev/null 2>&1

# The above line is parsed by OCaml as an opening comment and by the
# shell as an impossible command which is ignored.  The line below is
# run by the shell and ignored by OCaml.

exec nbdkit cc "$0" CC=ocamlopt CFLAGS="-output-obj -runtime-variant _pic $OCAML_STD_INCLUDES $OCAML_PLUGIN_LIBRARIES NBDKit.cmx -cclib -L../plugins/ocaml/.libs -cclib -lnbdkitocaml" "$@"
*)

open Printf

let disk = ref (Bytes.make (1024*1024) '\000')

let config k v =
  match k with
  | "size" ->
     let size = NBDKit.parse_size v in
     let size = Int64.to_int size in
     disk := Bytes.make size '\000'
  | _ ->
     failwith (sprintf "unknown parameter: %s" k)

let open_connection _ = ()

let get_size () = Bytes.length !disk |> Int64.of_int

let pread () buf offset _ =
  let len = NBDKit.buf_len buf in
  let offset = Int64.to_int offset in
  NBDKit.blit_bytes_to_buf !disk offset buf 0 len

let pwrite () buf offset _ =
  let len = NBDKit.buf_len buf in
  let offset = Int64.to_int offset in
  NBDKit.blit_buf_to_bytes buf 0 !disk offset len

let () =
  NBDKit.register_plugin
    ~name:    "cc-shebang.ml"
    ~version: (NBDKit.version ())
    ~config
    ~open_connection
    ~get_size
    ~pread
    ~pwrite
    ()
