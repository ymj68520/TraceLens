#----------------------------------------------------------------
# Generated CMake target import file.
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "duckx::duckx" for configuration ""
set_property(TARGET duckx::duckx APPEND PROPERTY IMPORTED_CONFIGURATIONS NOCONFIG)
set_target_properties(duckx::duckx PROPERTIES
  IMPORTED_LINK_INTERFACE_LANGUAGES_NOCONFIG "C;CXX"
  IMPORTED_LOCATION_NOCONFIG "${_IMPORT_PREFIX}/lib/libduckx.a"
  )

list(APPEND _cmake_import_check_targets duckx::duckx )
list(APPEND _cmake_import_check_files_for_duckx::duckx "${_IMPORT_PREFIX}/lib/libduckx.a" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
