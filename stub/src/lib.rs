//! PATH-shadow helper for battest external command mocks.
//!
//! Copied as `<command>.exe` into a mock directory. Sidecar files:
//! `<command>.stdout`, `<command>.stderr`, `<command>.exit`.
//! Call log: `_calls/<command>.log`.

use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

/// Directory and command stem derived from the stub executable path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StubContext {
    /// Directory that contains the stub and sidecar files.
    pub directory: PathBuf,
    /// File stem used for sidecars and the call log (`ipconfig`, `net`, …).
    pub stem: String,
}

/// Derive the mock directory and command stem from the running executable.
#[must_use]
pub fn stub_context(exe: &Path) -> StubContext {
    let directory = match exe.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => parent.to_path_buf(),
        _ => PathBuf::from("."),
    };
    let stem = exe
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("stub")
        .to_owned();
    StubContext { directory, stem }
}

/// Return `<dir>/<stem>.<suffix>`.
#[must_use]
pub fn sidecar(dir: &Path, stem: &str, suffix: &str) -> PathBuf {
    dir.join(format!("{stem}.{suffix}"))
}

/// Return `<dir>/_calls/<stem>.log`.
#[must_use]
pub fn call_log_path(dir: &Path, stem: &str) -> PathBuf {
    dir.join("_calls").join(format!("{stem}.log"))
}

/// Copy a sidecar file to `dest`. Missing files are treated as empty.
pub fn pipe_file(path: &Path, dest: &mut impl Write) -> io::Result<()> {
    let mut source = match fs::File::open(path) {
        Ok(file) => file,
        Err(err) if err.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(err) => return Err(err),
    };
    io::copy(&mut source, dest)?;
    Ok(())
}

/// Read an exit code from a sidecar file. Missing or invalid files yield `0`.
#[must_use]
pub fn read_exit_code(path: &Path) -> u8 {
    let Ok(text) = fs::read_to_string(path) else {
        return 0;
    };
    text.trim().parse::<u8>().unwrap_or(0)
}

/// Append a single argv line to the call log, creating parent directories.
pub fn append_args(log_path: &Path, args: &[String]) -> io::Result<()> {
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

#[cfg(test)]
mod tests {
    use super::{
        append_args, call_log_path, pipe_file, read_exit_code, sidecar, stub_context,
    };
    use std::env;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_DIR_SEQ: AtomicU64 = AtomicU64::new(0);

    fn make_temp_dir() -> PathBuf {
        let seq = TEST_DIR_SEQ.fetch_add(1, Ordering::Relaxed);
        let path = env::temp_dir()
            .join(format!("battest-stub-unit-{}-{seq}", std::process::id()));
        fs::create_dir_all(&path).expect("create temp dir");
        path
    }

    fn remove_temp_dir(path: &Path) {
        let _ = fs::remove_dir_all(path);
    }

    #[test]
    fn stub_context_uses_parent_and_stem() {
        let exe = PathBuf::from("mocks").join("ipconfig.exe");
        let context = stub_context(&exe);
        assert_eq!(context.directory, PathBuf::from("mocks"));
        assert_eq!(context.stem, "ipconfig");
    }

    #[test]
    fn stub_context_defaults_when_parent_missing() {
        let context = stub_context(Path::new("net.exe"));
        assert_eq!(context.directory, PathBuf::from("."));
        assert_eq!(context.stem, "net");
    }

    #[test]
    fn sidecar_and_call_log_paths() {
        let dir = Path::new("mockdir");
        assert_eq!(sidecar(dir, "net", "exit"), dir.join("net.exit"));
        assert_eq!(
            call_log_path(dir, "net"),
            dir.join("_calls").join("net.log")
        );
    }

    #[test]
    fn read_exit_code_missing_invalid_and_valid() {
        let dir = make_temp_dir();
        let missing = dir.join("missing.exit");
        assert_eq!(read_exit_code(&missing), 0);
        let invalid = dir.join("bad.exit");
        fs::write(&invalid, "nope\n").expect("write invalid");
        assert_eq!(read_exit_code(&invalid), 0);
        let overflow = dir.join("overflow.exit");
        fs::write(&overflow, "256").expect("write overflow");
        assert_eq!(read_exit_code(&overflow), 0);
        let valid = dir.join("ok.exit");
        fs::write(&valid, "  2 \n").expect("write valid");
        assert_eq!(read_exit_code(&valid), 2);
        remove_temp_dir(&dir);
    }

    #[test]
    fn pipe_file_copies_bytes_and_ignores_missing() {
        let dir = make_temp_dir();
        let present = dir.join("out.stdout");
        fs::write(&present, b"hello\0world").expect("write stdout sidecar");
        let mut buffer = Vec::new();
        pipe_file(&present, &mut buffer).expect("pipe present");
        assert_eq!(buffer, b"hello\0world");
        buffer.clear();
        pipe_file(&dir.join("missing.stdout"), &mut buffer).expect("pipe missing");
        assert!(buffer.is_empty());
        let mut ignored = Vec::new();
        assert!(pipe_file(&dir, &mut ignored).is_err());
        remove_temp_dir(&dir);
    }

    #[test]
    fn append_args_creates_log_and_appends() {
        let dir = make_temp_dir();
        let log_path = call_log_path(&dir, "ipconfig");
        append_args(&log_path, &["/flushdns".to_owned()]).expect("first append");
        append_args(&log_path, &["/all".to_owned(), "/x".to_owned()]).expect("second");
        append_args(&log_path, &[]).expect("empty argv");
        let text = fs::read_to_string(&log_path).expect("read log");
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines, ["/flushdns", "/all /x", ""]);
        remove_temp_dir(&dir);
    }
}
