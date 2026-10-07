The sole purpose of this directory is to serve as a test crate for checking if Cargo is usable.
`cargo test`, `cargo doc` and `cargo fmt` are run in the Autoconf script in this directory. If any of the commands fails,
Cargo is assumed not to be usable and the Rust bindings will be disabled.
