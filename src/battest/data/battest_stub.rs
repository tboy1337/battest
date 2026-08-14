//! PATH-shadow helper copied as `<command>.exe` into a mock directory.
//! Sidecars: `<command>.stdout`, `<command>.stderr`, `<command>.exit`
//! Call log: `_calls/<command>.log`

use std::env;
use std::fs::{self, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

fn sidecar(dir: &Path, stem: &str, suffix: &str) -> PathBuf {
    dir.join(format!("{stem}.{suffix}"))
}

fn pipe_file(path: &Path, dest: &mut dyn Write) {
    let Ok(mut source) = fs::File::open(path) else {
        return;
    };
    let mut buffer = [0_u8; 4096];
    loop {
        let Ok(read_bytes) = source.read(&mut buffer) else {
            break;
        };
        if read_bytes == 0 {
            break;
        }
        let _ = dest.write_all(&buffer[..read_bytes]);
    }
}

fn read_exit_code(path: &Path) -> u8 {
    let Ok(text) = fs::read_to_string(path) else {
        return 0;
    };
    text.trim().parse::<u8>().unwrap_or(0)
}

fn append_args(log_path: &Path, args: &[String]) -> io::Result<()> {
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)?;
    writeln!(log_file, "{}", args.join(" "))?;
    Ok(())
}

fn main() -> ExitCode {
    let exe = env::current_exe().unwrap_or_else(|_| PathBuf::from("stub.exe"));
    let dir = exe.parent().map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("."));
    let stem = exe
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("stub");
    let args: Vec<String> = env::args().skip(1).collect();
    let log_path = dir.join("_calls").join(format!("{stem}.log"));
    let _ = append_args(&log_path, &args);
    pipe_file(&sidecar(&dir, stem, "stdout"), &mut io::stdout());
    pipe_file(&sidecar(&dir, stem, "stderr"), &mut io::stderr());
    ExitCode::from(read_exit_code(&sidecar(&dir, stem, "exit")))
}
