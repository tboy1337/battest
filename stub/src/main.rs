//! PATH-shadow helper copied as `<command>.exe` into a mock directory.

use std::process::ExitCode;

fn main() -> ExitCode {
    ExitCode::from(battest_stub::run())
}
