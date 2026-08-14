//! PATH-shadow helper for battest external command mocks.
//!
//! Copied as `<command>.exe` into a mock directory. Sidecar files:
//! `<command>.stdout`, `<command>.stderr`, `<command>.exit`.
//! Call log: `_calls/<command>.log` is appended only when that file already exists.

use std::env;
use std::fmt::Write as _;
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

/// Encode argv as a JSON array of strings without extra crates.
#[must_use]
pub fn encode_argv_json(args: &[String]) -> String {
    let mut out = String::from("[");
    for (index, arg) in args.iter().enumerate() {
        if index > 0 {
            out.push(',');
        }
        push_json_string(&mut out, arg);
    }
    out.push(']');
    out
}

fn push_json_string(out: &mut String, value: &str) {
    out.push('"');
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", u32::from(c));
            }
            c => out.push(c),
        }
    }
    out.push('"');
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
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)?;
        }
    }
    let mut log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)?;
    writeln!(log_file, "{}", encode_argv_json(args))?;
    Ok(())
}

/// Use `current` when `env::current_exe` succeeds; otherwise `stub.exe`.
#[must_use]
pub fn resolve_exe(current: io::Result<PathBuf>) -> PathBuf {
    current.unwrap_or_else(|_| PathBuf::from("stub.exe"))
}

/// Execute the stub using `exe` and `args`, writing sidecars to `stdout`/`stderr`.
#[must_use]
pub fn run_with(
    exe: &Path,
    args: &[String],
    stdout: &mut impl Write,
    stderr: &mut impl Write,
) -> u8 {
    let context = stub_context(exe);
    let log_path = call_log_path(&context.directory, &context.stem);
    if log_path.is_file() && append_args(&log_path, args).is_err() {
        return 1;
    }
    if pipe_file(
        &sidecar(&context.directory, &context.stem, "stdout"),
        stdout,
    )
    .is_err()
    {
        return 1;
    }
    if pipe_file(
        &sidecar(&context.directory, &context.stem, "stderr"),
        stderr,
    )
    .is_err()
    {
        return 1;
    }
    read_exit_code(&sidecar(&context.directory, &context.stem, "exit"))
}

/// Run the stub for `current` executable and `args`.
#[must_use]
pub fn run_from(current: io::Result<PathBuf>, args: &[String]) -> u8 {
    let mut stdout = io::stdout();
    let mut stderr = io::stderr();
    run_with(&resolve_exe(current), args, &mut stdout, &mut stderr)
}

/// Run the PATH-shadow stub for this process executable and argv.
#[must_use]
pub fn run() -> u8 {
    let args: Vec<String> = env::args().skip(1).collect();
    run_from(env::current_exe(), &args)
}

#[cfg(test)]
mod tests {
    use super::{
        append_args, call_log_path, encode_argv_json, pipe_file, read_exit_code,
        resolve_exe, run_from, run_with, sidecar, stub_context,
    };
    use std::env;
    use std::fs;
    use std::io::{self, Write};
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_DIR_SEQ: AtomicU64 = AtomicU64::new(0);

    struct RestoreCwd(PathBuf);

    impl Drop for RestoreCwd {
        fn drop(&mut self) {
            let _ = env::set_current_dir(&self.0);
        }
    }

    struct FailingWriter;

    impl Write for FailingWriter {
        fn write(&mut self, _buf: &[u8]) -> io::Result<usize> {
            Err(io::Error::other("write failed"))
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    fn make_temp_dir() -> PathBuf {
        let seq = TEST_DIR_SEQ.fetch_add(1, Ordering::Relaxed);
        let path = env::temp_dir()
            .join(format!("battest-stub-unit-{}-{seq}", std::process::id()));
        fs::create_dir_all(&path).expect("create temp dir");
        path
    }

    fn remove_temp_dir(path: &Path) {
        for _ in 0..20 {
            if fs::remove_dir_all(path).is_ok() {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
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
    fn stub_context_defaults_stem_when_file_stem_missing() {
        let context = stub_context(Path::new("/"));
        assert_eq!(context.stem, "stub");
    }

    #[cfg(windows)]
    #[test]
    fn stub_context_defaults_stem_when_not_utf8() {
        use std::ffi::OsString;
        use std::os::windows::ffi::OsStringExt;

        let dir = make_temp_dir();
        let name = OsString::from_wide(&[0xD800]);
        let exe = dir.join(name);
        let context = stub_context(&exe);
        assert_eq!(context.stem, "stub");
        remove_temp_dir(&dir);
    }

    #[cfg(unix)]
    #[test]
    fn stub_context_defaults_stem_when_not_utf8() {
        use std::ffi::OsString;
        use std::os::unix::ffi::OsStringExt;

        let dir = make_temp_dir();
        let exe = dir.join(OsString::from_vec(vec![0xff]));
        let context = stub_context(&exe);
        assert_eq!(context.stem, "stub");
        remove_temp_dir(&dir);
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
        let empty = dir.join("empty.exit");
        fs::write(&empty, "   \n").expect("write empty");
        assert_eq!(read_exit_code(&empty), 0);
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
    fn pipe_file_fails_when_destination_write_fails() {
        let dir = make_temp_dir();
        let present = dir.join("out.stdout");
        fs::write(&present, b"payload").expect("write stdout sidecar");
        let mut writer = FailingWriter;
        assert!(pipe_file(&present, &mut writer).is_err());
        assert!(writer.flush().is_ok());
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
        assert_eq!(lines, [r#"["/flushdns"]"#, r#"["/all","/x"]"#, "[]",]);
        remove_temp_dir(&dir);
    }

    #[test]
    fn append_args_filename_only_writes_in_cwd() {
        let dir = make_temp_dir();
        let previous = env::current_dir().expect("cwd");
        let _restore = RestoreCwd(previous.clone());
        env::set_current_dir(&dir).expect("chdir");
        append_args(Path::new("flat.log"), &["z".to_owned()])
            .expect("append filename-only");
        let text = fs::read_to_string(dir.join("flat.log")).expect("read");
        assert_eq!(text.lines().collect::<Vec<_>>(), [r#"["z"]"#]);
        env::set_current_dir(&previous).expect("restore cwd");
        remove_temp_dir(&dir);
    }

    #[test]
    fn append_args_when_path_has_no_parent() {
        let err = append_args(Path::new(""), &["x".to_owned()]);
        assert!(err.is_err());
    }

    #[test]
    fn append_args_fails_when_parent_is_a_file() {
        let dir = make_temp_dir();
        let blocker = dir.join("blocker");
        fs::write(&blocker, b"x").expect("write blocker");
        let log_path = blocker.join("child.log");
        assert!(append_args(&log_path, &["a".to_owned()]).is_err());
        remove_temp_dir(&dir);
    }

    #[test]
    fn append_args_fails_when_path_is_directory() {
        let dir = make_temp_dir();
        assert!(append_args(&dir, &["a".to_owned()]).is_err());
        remove_temp_dir(&dir);
    }

    #[test]
    fn resolve_exe_uses_ok_path_or_fallback() {
        let ok = PathBuf::from("mocks").join("net.exe");
        assert_eq!(resolve_exe(Ok(ok.clone())), ok);
        let fallback = resolve_exe(Err(io::Error::other("missing")));
        assert_eq!(fallback, PathBuf::from("stub.exe"));
    }

    #[test]
    fn run_with_sidecars_log_and_io_errors() {
        let dir = make_temp_dir();
        let exe = dir.join("tool.exe");
        fs::write(dir.join("tool.stdout"), b"out").expect("stdout");
        fs::write(dir.join("tool.stderr"), b"err").expect("stderr");
        fs::write(dir.join("tool.exit"), "4").expect("exit");
        let log_path = call_log_path(&dir, "tool");
        fs::create_dir_all(log_path.parent().expect("log parent")).expect("calls dir");
        fs::write(&log_path, "").expect("empty log");
        let mut stdout = Vec::new();
        let mut stderr = Vec::new();
        let code = run_with(&exe, &["/all".to_owned()], &mut stdout, &mut stderr);
        assert_eq!(code, 4);
        assert_eq!(stdout, b"out");
        assert_eq!(stderr, b"err");
        let log = fs::read_to_string(&log_path).expect("read log");
        assert_eq!(log.lines().collect::<Vec<_>>(), [r#"["/all"]"#]);

        let mut empty_out = Vec::new();
        let mut empty_err = Vec::new();
        let skipped = run_with(
            &dir.join("other.exe"),
            &["x".to_owned()],
            &mut empty_out,
            &mut empty_err,
        );
        assert_eq!(skipped, 0);
        assert!(empty_out.is_empty());
        assert!(!call_log_path(&dir, "other").exists());

        fs::create_dir_all(dir.join("broken.stdout")).expect("stdout dir");
        fs::create_dir_all(call_log_path(&dir, "broken")).expect("log path is dir");
        let mut ignored_out = Vec::new();
        let mut ignored_err = Vec::new();
        let failed = run_with(
            &dir.join("broken.exe"),
            &["y".to_owned()],
            &mut ignored_out,
            &mut ignored_err,
        );
        assert_eq!(failed, 1);
        remove_temp_dir(&dir);
    }

    #[test]
    fn encode_argv_json_escapes_quotes_and_controls() {
        assert_eq!(encode_argv_json(&[]), "[]");
        assert_eq!(
            encode_argv_json(&["a\"b".to_owned(), "c\\d".to_owned()]),
            r#"["a\"b","c\\d"]"#
        );
        assert_eq!(encode_argv_json(&["foo bar".to_owned()]), r#"["foo bar"]"#);
        let with_controls = encode_argv_json(&["a\n\r\t\u{0001}".to_owned()]);
        assert_eq!(with_controls, r#"["a\n\r\t\u0001"]"#);
    }

    #[test]
    fn run_from_uses_isolated_exe() {
        let dir = make_temp_dir();
        let exe = dir.join("tool.exe");
        fs::write(&exe, b"stub").expect("write exe placeholder");
        fs::write(dir.join("tool.exit"), "7").expect("exit");
        let code = run_from(Ok(exe), &["/x".to_owned()]);
        assert_eq!(code, 7);
        remove_temp_dir(&dir);
    }

    #[test]
    fn run_wrapper_without_sidecars() {
        let _ = super::run();
    }
}
