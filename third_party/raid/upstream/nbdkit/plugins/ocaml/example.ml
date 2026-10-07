(* Example OCaml plugin.

   This example can be freely copied and used for any purpose.

   When building nbdkit this example is compiled as:

     plugins/ocaml/nbdkit-ocamlexample-plugin.so

   You can run it from the build directory like this:

     ./nbdkit -f -v plugins/ocaml/nbdkit-ocamlexample-plugin.so

   or specify the size of the disk:

     ./nbdkit -f -v plugins/ocaml/nbdkit-ocamlexample-plugin.so 100M

   and connect to it with guestfish like this:

     guestfish --format=raw -a nbd://localhost
     ><fs> run
     ><fs> part-disk /dev/sda mbr
     ><fs> mkfs ext2 /dev/sda1
     ><fs> list-filesystems
     ><fs> mount /dev/sda1 /
     ><fs> [etc]
*)

(* Disk image with default size. *)
let disk = ref (Bytes.make (1024*1024) '\000')

(* This is called when the plugin is loaded. *)
let load () =
  (* Debugging output is only printed when the server is in
   * verbose mode (nbdkit -v option).
   *)
  NBDKit.debug "example OCaml plugin loaded"

(* This is called when the plugin is unloaded. *)
let unload () =
  NBDKit.debug "example OCaml plugin unloaded"

(* Add some extra fields to --dump-plugin output.
 * To test this from the build directory:
 *   ./nbdkit --dump-plugin plugins/ocaml/nbdkit-ocamlexample-plugin.so
 *)
let dump_plugin () =
  Printf.printf "ocamlexample_data=42\n";
  flush stdout

(* This is called for every [key=value] parameter passed to the plugin
 * on the command line.
 *)
let config key value =
  match key with
  | "size" ->
     let size = Int64.to_int (NBDKit.parse_size value) in
     disk := Bytes.make size '\000' (* Reallocate the disk. *)
  | _ ->
     failwith (Printf.sprintf "unknown parameter: %s" key)

(* A debug flag (see example-debug-flag.c) *)
external ocamlexample_debug_foo : unit -> int =
  "get_ocamlexample_debug_foo" [@@noalloc]

(* Any type (even unit) can be used as a per-connection handle.
 * This is just an example.  The same value that you return from
 * your [open_connection] function is passed back as the first
 * parameter to connected functions like get_size and pread.
 *)
type handle = {
  h_id : int; (* just a useless example field *)
}

let id = ref 0

(* An NBD client has opened a connection. *)
let open_connection readonly =
  let export_name = NBDKit.export_name () in
  NBDKit.debug "example OCaml plugin handle opened readonly=%b export=%S"
    readonly export_name;
  NBDKit.debug "debug flag: -D ocamlexample.foo=%d" (ocamlexample_debug_foo ());
  incr id;
  { h_id = !id }

(* Return the size of the disk. *)
let get_size h =
  NBDKit.debug "example OCaml plugin get_size id=%d" h.h_id;
  Int64.of_int (Bytes.length !disk)

(* Read part of the disk.  This should modify the buf parameter
 * directly as shown below.
 *)
let pread h buf offset _ =
  let len = NBDKit.buf_len buf in
  let offset = Int64.to_int offset in
  NBDKit.blit_bytes_to_buf !disk offset buf 0 len

(* Write part of the disk. *)
let pwrite h buf offset _ =
  let len = NBDKit.buf_len buf in
  let offset = Int64.to_int offset in
  NBDKit.blit_buf_to_bytes buf 0 !disk offset len

(* Set the plugin thread model.  [SERIALIZE_ALL_REQUESTS] is a
 * safe default.
 *)
let thread_model () =
  NBDKit.THREAD_MODEL_SERIALIZE_ALL_REQUESTS

(* Version is optional.  If used, it can be any string. *)
let version =
  (* You can return a normal version string such as "1.0"
   * or call this function which returns the version of
   * nbdkit at compile time:
   *)
  NBDKit.version ()

(* The plugin must be registered once by calling [register_plugin].
 * name, open_connection, get_size and pread are required,
 * everything else is optional.
 *)
let () =
  NBDKit.register_plugin
    ~name: "ocamlexample"
    ~version
    ~load
    ~unload
    ~dump_plugin
    ~config
    ~magic_config_key: "size"
    ~open_connection
    ~get_size
    ~pread
    ~pwrite
    ~thread_model
    ()
