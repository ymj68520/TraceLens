/* Example OCaml plugin.

   This example can be freely copied and used for any purpose.

   This shows how to use debug flags with OCaml plugins.  For
   a description of debug flags see "Debug Flags" in nbdkit-plugin(3). */

#include <caml/mlvalues.h>
#define NBDKIT_API_VERSION 2
#include "nbdkit-plugin.h"

/* This is the debug flag.
 *
 * The debug flag is set by nbdkit when you use '-D ocamlexample.foo=<N>'.
 */
NBDKIT_DLL_PUBLIC int ocamlexample_debug_foo = 0;

/* To fetch the value of the debug flag from OCaml code we call this.
 * NB: noalloc function.
 */
NBDKIT_DLL_PUBLIC value
get_ocamlexample_debug_foo (value unitv)
{
  return Val_int (ocamlexample_debug_foo);
}
