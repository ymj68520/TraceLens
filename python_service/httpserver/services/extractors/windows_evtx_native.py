"""Reuse the existing native libevtx for XML variants python-evtx cannot decode.

Normal records only. Index and record ID must agree before returning any XML.
No recovery record or path fallback is permitted here.
"""
import ctypes
import ctypes.util
import os


class NativeEvtxReader:
    def __init__(self, path):
        self.library = None
        self.handle = ctypes.c_void_p()
        self.path = path
        self.attempted = False
        self.version = None

    def _function(self, name, args, result=ctypes.c_int):
        fn = getattr(self.library, name)
        fn.argtypes, fn.restype = args, result
        return fn

    def _open(self):
        if self.attempted:
            return bool(self.handle)
        self.attempted = True
        try:
            name = ctypes.util.find_library("evtx")
            if not name:
                return False
            self.library = ctypes.CDLL(name)
            ptr = ctypes.c_void_p
            ref = ctypes.POINTER(ptr)
            self._free = self._function("libevtx_file_free", [ref, ptr])
            self._close = self._function("libevtx_file_close", [ptr, ptr])
            init = self._function("libevtx_file_initialize", [ref, ptr])
            open_file = self._function("libevtx_file_open", [ptr, ctypes.c_char_p, ctypes.c_int, ptr])
            self._get = self._function("libevtx_file_get_record_by_index", [ptr, ctypes.c_int, ref, ptr])
            self._record_free = self._function("libevtx_record_free", [ref, ptr])
            self._id = self._function("libevtx_record_get_identifier", [ptr, ctypes.POINTER(ctypes.c_uint64), ptr])
            self._size = self._function("libevtx_record_get_utf8_xml_string_size", [ptr, ctypes.POINTER(ctypes.c_size_t), ptr])
            self._xml = self._function("libevtx_record_get_utf8_xml_string", [ptr, ptr, ctypes.c_size_t, ptr])
            self.version = self._function("libevtx_get_version", [], ctypes.c_char_p)().decode("ascii")
            if init(ctypes.byref(self.handle), None) != 1 or open_file(self.handle, os.fsencode(self.path), 1, None) != 1:
                self.close()
                return False
            return True
        except (OSError, AttributeError, ValueError):
            self.close()
            return False

    def read_xml(self, index, expected_id):
        if index < 0 or expected_id is None or not self._open():
            raise ValueError("EVTX_NATIVE_PARSER_UNAVAILABLE")
        record = ctypes.c_void_p()
        try:
            if self._get(self.handle, index, ctypes.byref(record), None) != 1:
                raise ValueError("EVTX_NATIVE_RECORD_UNAVAILABLE")
            record_id, size = ctypes.c_uint64(), ctypes.c_size_t()
            if self._id(record, ctypes.byref(record_id), None) != 1 or record_id.value != expected_id:
                raise ValueError("EVTX_NATIVE_RECORD_ID_MISMATCH")
            if self._size(record, ctypes.byref(size), None) != 1 or not 1 <= size.value <= 8 * 1024 * 1024:
                raise ValueError("EVTX_NATIVE_XML_SIZE_INVALID")
            buffer = ctypes.create_string_buffer(size.value)
            if self._xml(record, buffer, size.value, None) != 1:
                raise ValueError("EVTX_NATIVE_XML_UNAVAILABLE")
            return buffer.value.decode("utf-8", errors="strict")
        finally:
            if record:
                self._record_free(ctypes.byref(record), None)

    def close(self):
        if self.handle:
            self._close(self.handle, None)
            self._free(ctypes.byref(self.handle), None)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
