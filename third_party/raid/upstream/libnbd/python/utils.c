/* NBD client library in userspace
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
 */

/* Miscellaneous helper functions for Python. */

#include <config.h>

#define PY_SSIZE_T_CLEAN 1
#include <Python.h>

#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <arpa/inet.h>
#include <netinet/in.h>

#include <libnbd.h>

#include "methods.h"

/* These two functions are used when parsing argv parameters. */
char **
nbd_internal_py_get_string_list (PyObject *obj)
{
  size_t i, len;
  char **r;

  assert (obj);

  if (!PyList_Check (obj)) {
    PyErr_SetString (PyExc_TypeError, "expecting a list parameter");
    return NULL;
  }

  Py_ssize_t slen = PyList_Size (obj);
  if (slen == -1) {
    PyErr_SetString (PyExc_RuntimeError,
                     "get_string_list: PyList_Size failure");
    return NULL;
  }
  len = (size_t)slen;
  r = malloc (sizeof (char *) * (len+1));
  if (r == NULL) {
    PyErr_NoMemory ();
    return NULL;
  }

  for (i = 0; i < len; ++i) {
    PyObject *bytes = PyUnicode_AsUTF8String (PyList_GetItem (obj, i));
    if (!bytes)
      goto err;
    r[i] = strdup (PyBytes_AS_STRING (bytes));
    Py_DECREF (bytes);
    if (r[i] == NULL) {
      PyErr_NoMemory ();
      goto err;
    }
  }
  r[len] = NULL;

  return r;

 err:
  while (i--)
    free (r[i]);
  free (r);
  return NULL;
}

void
nbd_internal_py_free_string_list (char **argv)
{
  size_t i;

  if (!argv)
    return;

  for (i = 0; argv[i] != NULL; ++i)
    free (argv[i]);
  free (argv);
}

/* Convert a Python object into a struct sockaddr, according to the
 * general rules described here:
 * https://docs.python.org/3/library/socket.html
 *
 * Because that mapping is not unique (it only makes sense in the
 * context of knowing the address family), the caller has to pass in
 * the address family as the first parameter.  Therefore the formats
 * that we parse are:
 *
 * ("AF_UNIX", path)
 * ("AF_UNIX", (path))
 * ("AF_INET", (addr, port))
 * ("AF_INET6", (addr, port, [additional elements ignored]))
 *
 * For backwards compatibility with libnbd <= 1.24, we also allow a
 * single string here which is parsed as a Unix domain socket.
 *
 * There is a function in cpython called getsockaddrarg which roughly
 * does the same thing, but in cpython they know the socket family
 * already.  In any case that function cannot be called directly.
 */
static int parse_path_to_sockaddr_un (PyObject *path,
                                      struct sockaddr_un *sun, socklen_t *len);
static int parse_addr_to_sockaddr_in (PyObject *tuple,
                                      struct sockaddr_in *sin, socklen_t *len);
static int parse_addr_to_sockaddr_in6 (PyObject *tuple,
                                       struct sockaddr_in6 *sin6,
                                       socklen_t *len);

int
nbd_internal_py_get_sockaddr (PyObject *addr,
                              struct sockaddr_storage *ss, socklen_t *len)
{
  memset (ss, 0, sizeof *ss);

  /* For backwards compatibility with libnbd <= 1.24, parse a bare
   * string as AF_UNIX.
   */
  if (PyUnicode_Check (addr)) {
    struct sockaddr_un *sun = (struct sockaddr_un *)ss;
    return parse_path_to_sockaddr_un (addr, sun, len);
  }

  else if (PyTuple_Check (addr)) {
    const char *af;
    Py_ssize_t n;
    PyObject *sockaddr;

    /* Must be a 2-element tuple. */
    n = PyTuple_Size (addr);
    if (n != 2) {
      PyErr_SetString (PyExc_RuntimeError,
                       "get_sockaddr: must be a 2-element tuple, "
                       "with the first element being the address family, "
                       "for example: (\"AF_UNIX\", path) or "
                       "(\"AF_INET\", (ipaddr, port))");
      return -1;
    }

    /* First element is the address family. */
    af = PyUnicode_AsUTF8 (PyTuple_GetItem (addr, 0));
    if (!af) return -1;

    /* Second element is the sockaddr. */
    sockaddr = PyTuple_GetItem (addr, 1);

    /* AF_UNIX */
    if (strcasecmp (af, "UNIX") == 0 || strcasecmp (af, "AF_UNIX") == 0) {
      if (PyTuple_Check (sockaddr) && PyTuple_Size (sockaddr) == 1)
        sockaddr = PyTuple_GetItem (sockaddr, 0);

      if (PyUnicode_Check (sockaddr)) {
        struct sockaddr_un *sun = (struct sockaddr_un *)ss;
        return parse_path_to_sockaddr_un (sockaddr, sun, len);
      }

      PyErr_SetString (PyExc_RuntimeError,
                       "get_sockaddr: wrong format for Unix domain socket");
      return -1;
    }

    /* AF_INET */
    else if (strcasecmp (af, "INET") == 0 ||
             strcasecmp (af, "AF_INET") == 0) {
      if (PyTuple_Check (sockaddr)) {
        struct sockaddr_in *sin = (struct sockaddr_in *)ss;
        return parse_addr_to_sockaddr_in (sockaddr, sin, len);
      }

      PyErr_SetString (PyExc_RuntimeError,
                       "get_sockaddr: wrong format for AF_INET socket");
      return -1;
    }

    /* AF_INET6 */
    else if (strcasecmp (af, "INET6") == 0 ||
             strcasecmp (af, "AF_INET6") == 0) {
      if (PyTuple_Check (sockaddr)) {
        struct sockaddr_in6 *sin6 = (struct sockaddr_in6 *)ss;
        return parse_addr_to_sockaddr_in6 (sockaddr, sin6, len);
      }

      PyErr_SetString (PyExc_RuntimeError,
                       "get_sockaddr: wrong format for AF_INET6 socket");
      return -1;
    }

    else {
      PyErr_SetString (PyExc_TypeError,
                       "get_sockaddr: unknown address family");
      return -1;
    }
  }

  else {
    PyErr_SetString (PyExc_TypeError, "get_sockaddr: "
                     "unknown socket address type");
    return -1;
  }
}

/* Parse path (which must be PyUnicode) to sockaddr_un. */
static int
parse_path_to_sockaddr_un (PyObject *path,
                           struct sockaddr_un *sun, socklen_t *len)
{
  const char *unixsocket;
  size_t namelen;

  sun->sun_family = AF_UNIX;
  *len = sizeof *sun;

  unixsocket = PyUnicode_AsUTF8 (path);
  if (!unixsocket) {
    PyErr_SetString (PyExc_TypeError, "get_sockaddr: cannot parse socket path");
    return -1;
  }
  namelen = strlen (unixsocket);
  if (namelen > sizeof sun->sun_path) {
    PyErr_SetString (PyExc_RuntimeError,
                     "get_sockaddr: Unix domain socket name too long");
    return -1;
  }
  memcpy (sun->sun_path, unixsocket, namelen);
  return 0;
}

/* Parse (addr, port) tuple (which must be PyTuple) to sockaddr_in. */
static int
parse_addr_to_sockaddr_in (PyObject *tuple,
                           struct sockaddr_in *sin, socklen_t *len)
{
  const char *addr_str, *port_str;
  int port;
  const Py_ssize_t n = PyTuple_Size (tuple);

  if (n < 2) {
    PyErr_SetString (PyExc_TypeError, "get_sockaddr: need (addr, port) "
                     "for socket address");
    return -1;
  }

  addr_str = PyUnicode_AsUTF8 (PyTuple_GetItem (tuple, 0));
  port_str = PyUnicode_AsUTF8 (PyTuple_GetItem (tuple, 1));

  if (!addr_str || !port_str) {
    PyErr_SetString (PyExc_TypeError, "get_sockaddr: cannot parse "
                     "address or port number in socket address");
    return -1;
  }

  sin->sin_family = AF_INET;
  *len = sizeof *sin;

  switch (inet_pton (AF_INET, addr_str, &sin->sin_addr)) {
  case 1: break; /* success */
  case 0: /* invalid address string */
    PyErr_SetString (PyExc_RuntimeError,
                     "get_sockaddr: inet_pton: cannot parse IPv4 address");
    return -1;
  case -1: /* invalid address family, probably impossible */
    PyErr_SetString (PyExc_RuntimeError,
                     "get_sockaddr: inet_pton: invalid address family");
    return -1;
  }

  if (sscanf (port_str, "%d", &port) != 1) {
    PyErr_SetString (PyExc_RuntimeError,
                     "get_sockaddr: cannot parse port number");
    return -1;
  }
  sin->sin_port = htons (port);

  return 0;
}

/* Parse (addr, port) tuple (which must be PyTuple) to sockaddr_in6. */
static int
parse_addr_to_sockaddr_in6 (PyObject *tuple,
                            struct sockaddr_in6 *sin6, socklen_t *len)
{
  const char *addr_str, *port_str;
  int port;
  const Py_ssize_t n = PyTuple_Size (tuple);

  if (n < 2) {
    PyErr_SetString (PyExc_TypeError, "get_sockaddr: need (addr, port) "
                     "for socket address");
    return -1;
  }

  /* element 2 = flowinfo, element 3 = scope_id, both are
   * currently ignored.
   */
  addr_str = PyUnicode_AsUTF8 (PyTuple_GetItem (tuple, 0));
  port_str = PyUnicode_AsUTF8 (PyTuple_GetItem (tuple, 1));

  if (!addr_str || !port_str) {
    PyErr_SetString (PyExc_TypeError, "get_sockaddr: cannot parse "
                     "address or port number in socket address");
    return -1;
  }

  sin6->sin6_family = AF_INET6;
  *len = sizeof *sin6;

  switch (inet_pton (AF_INET6, addr_str, &sin6->sin6_addr)) {
  case 1: break; /* success */
  case 0: /* invalid address string */
    PyErr_SetString (PyExc_RuntimeError,
                     "get_sockaddr: inet_pton: cannot parse IPv6 address");
    return -1;
  case -1: /* invalid address family, probably impossible */
    PyErr_SetString (PyExc_RuntimeError,
                     "get_sockaddr: inet_pton: invalid address family");
    return -1;
  }

  if (sscanf (port_str, "%d", &port) != 1) {
    PyErr_SetString (PyExc_RuntimeError,
                     "get_sockaddr: cannot parse port number");
    return -1;
  }
  sin6->sin6_port = htons (port);

  return 0;
}

/* Obtain the type object for nbd.Buffer */
PyObject *
nbd_internal_py_get_nbd_buffer_type (void)
{
  static PyObject *type;

  if (!type) {
    PyObject *modname = PyUnicode_FromString ("nbd");
    PyObject *module = PyImport_Import (modname);
    assert (module);
    type = PyObject_GetAttrString (module, "Buffer");
    assert (type);
    Py_DECREF (modname);
    Py_DECREF (module);
  }
  return type;
}

/* Helper to package callback *error into modifiable PyObject */
PyObject *
nbd_internal_py_wrap_errptr (int err)
{
  static PyObject *py_ctypes_mod;

  if (!py_ctypes_mod) {
    PyObject *py_modname = PyUnicode_FromString ("ctypes");
    if (!py_modname)
      return NULL;
    py_ctypes_mod = PyImport_Import (py_modname);
    Py_DECREF (py_modname);
    if (!py_ctypes_mod)
      return NULL;
  }

  return PyObject_CallMethod (py_ctypes_mod, "c_int", "i", err);
}

/* Helper to compute view.toreadonly()[start:end] in chunk callback */
PyObject *
nbd_internal_py_get_subview (PyObject *view, const char *subbuf, size_t count)
{
  Py_buffer *orig;
  const char *base;
  PyObject *start, *end, *slice;
  PyObject *ret;

  assert (PyMemoryView_Check (view));
  orig = PyMemoryView_GET_BUFFER (view);
  assert (PyBuffer_IsContiguous (orig, 'A'));
  base = orig->buf;
  assert (subbuf >= base && count <= orig->len &&
          subbuf + count <= base + orig->len);
  start = PyLong_FromLong (subbuf - base);
  if (!start) return NULL;
  end = PyLong_FromLong (subbuf - base + count);
  if (!end) { Py_DECREF (start); return NULL; }
  slice = PySlice_New (start, end, NULL);
  Py_DECREF (start);
  Py_DECREF (end);
  if (!slice) return NULL;
  ret = PyObject_GetItem (view, slice);
  Py_DECREF (slice);
  /* memoryview.toreadonly() was only added in Python 3.8.
   * PyMemoryView_GetContiguous (ret, PyBuf_READ, 'A') doesn't force readonly.
   * So we mess around directly with the Py_buffer.
   */
  if (ret)
    PyMemoryView_GET_BUFFER (ret)->readonly = 1;
  return ret;
}
