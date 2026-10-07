# Example Python plugin.
#
# This example can be freely used for any purpose.

# Run it from the build directory like this:
#
#   ./nbdkit -f -v python ./plugins/python/examples/ramdisk.py test1=foo
#
# Or run it after installing nbdkit like this:
#
#   nbdkit -f -v python ./plugins/python/examples/ramdisk.py test1=foo
#
# The -f -v arguments are optional.  They cause the server to stay in
# the foreground and print debugging, which is useful when testing.
#
# You can connect to the server using guestfish or qemu, eg:
#
#   guestfish --format=raw -a nbd://localhost
#   ><fs> run
#   ><fs> part-disk /dev/sda mbr
#   ><fs> mkfs ext2 /dev/sda1
#   ><fs> list-filesystems
#   ><fs> mount /dev/sda1 /
#   ><fs> [etc]

import nbdkit
import errno

# This is the string used to store the emulated disk (initially all
# zero bytes).  There is one disk per nbdkit instance, so if you
# reconnect to the same server you should see the same disk.  You
# could also put this into the handle, so there would be a fresh disk
# per handle.
disk = bytearray(1024 * 1024)


# There are several variants of the API.  nbdkit will use this
# constant to determine which one you want to use.  This is the latest
# version at the time this example was written.
API_VERSION = 2


# This just prints the extra command line parameters, but real plugins
# should parse them and reject any unknown parameters.
def config(key, value):
    nbdkit.debug("ignored parameter %s=%s" % (key, value))


def open(readonly):
    nbdkit.debug("open: readonly=%d, tls=%r" % (readonly, nbdkit.is_tls()))

    # You can return any Python object from open (even None), and the
    # same object will be passed as the first arg 'h' to the other
    # callbacks below.  To return an error from this method you must
    # throw an exception.
    return 1


def get_size(h):
    return len(disk)


def pread(h, buf, offset, flags):
    end = offset + len(buf)
    buf[:] = disk[offset:end]
    #  or if reading from a file you can use:
    # f.readinto(buf)


def pwrite(h, buf, offset, flags):
    end = offset + len(buf)
    disk[offset:end] = buf


def zero(h, count, offset, flags):
    if flags & nbdkit.FLAG_MAY_TRIM:
        disk[offset:offset+count] = bytearray(count)
    else:
        nbdkit.set_error(errno.EOPNOTSUPP)
        raise Exception
