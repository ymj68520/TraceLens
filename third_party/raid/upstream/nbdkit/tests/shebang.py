#!../nbdkit python

disk = bytearray(1024 * 1024)


def open(readonly):
    print("open: readonly=%d" % readonly)
    return 1


def get_size(h):
    return len(disk)


def pread(h, buf, offset):
    end = offset + len(buf)
    buf[:] = disk[offset:end]
