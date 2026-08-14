//! PATH-shadow helper copied as `<command>.exe` into a mock directory.

use std::env;
use std::io;
use std::path::PathBuf;
use std::process::ExitCode;

use battest_stub::{
    append_args, call_log_path, pipe_file, read_exit_code, sidecar, stub_context,
};

fn main() -> ExitCode {
    let exe = env::current_exe().unwrap_or_else(|_| PathBuf::from("stub.exe"));
    let context = stub_context(&exe);
    let args: Vec<String> = env::args().skip(1).collect();
    let _ = append_args(&call_log_path(&context.directory, &context.stem), &args);
    let _ = pipe_file(
        &sidecar(&context.directory, &context.stem, "stdout"),
        &mut io::stdout(),
    );
    let _ = pipe_file(
        &sidecar(&context.directory, &context.stem, "stderr"),
        &mut io::stderr(),
    );
    ExitCode::from(read_exit_code(&sidecar(
        &context.directory,
        &context.stem,
        "exit",
    )))
}
