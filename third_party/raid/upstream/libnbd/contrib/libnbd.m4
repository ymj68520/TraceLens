# libnbd.m4 serial 1
dnl Copyright (C) 2024 Free Software Foundation, Inc.
dnl This file is free software; the Free Software Foundation
dnl gives unlimited permission to copy and/or distribute it,
dnl with or without modifications, as long as this notice is preserved.

dnl From Bruno Haible, 2024.

# Test for compiler options needed for using libnbd:
# LIBNBD_CFLAGS
# LIBNBD_LIBS
# If LIBNBD_LIBS comes out as empty, libnbd was not found.
AC_DEFUN([CHECK_LIBNBD],
[
  PKG_CHECK_MODULES([LIBNBD], [libnbd],
    [dnl Test whether libnbd is really present. This is needed for bi-arch
     dnl systems: libnbd may be installed only in 64-bit mode, and the
     dnl libnbd.pc file will then also be found in 32-bit mode, for which no
     dnl library is installed.
     saved_CFLAGS=$CFLAGS
     saved_LIBS=$LIBS
     CFLAGS="$CFLAGS $LIBNBD_CFLAGS"
     LIBS="$LIBS $LIBNBD_LIBS"
     AC_LINK_IFELSE(
       [AC_LANG_PROGRAM(
          [[#include <libnbd.h>]],
          [[return nbd_get_errno ();]])
       ],
       [dnl Yes it is present.
        AC_DEFINE([HAVE_LIBNBD], [1], [libnbd found at compile time])
        AC_PATH_PROGS([NBDKIT], [nbdkit], [no], [$PATH:/usr/local/sbin:/usr/sbin])
       ],
       [dnl Nope, pkg-config fooled us.
        LIBNBD_CFLAGS=
        LIBNBD_LIBS=
       ])
     LIBS=$saved_LIBS
     CFLAGS=$saved_CFLAGS
    ],
    [LIBNBD_CFLAGS=
     LIBNBD_LIBS=
    ])
  AC_SUBST([LIBNBD_CFLAGS])
  AC_SUBST([LIBNBD_LIBS])
])
